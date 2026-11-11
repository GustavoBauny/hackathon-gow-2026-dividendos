"""Passos dos cenários de tests/features/bureau.feature.

O bureau é simulado por um servidor HTTP de verdade na rede local: o cliente usa `requests`, timeouts
e retry reais, e o roteiro de cada cliente diz o que a API responde a cada chamada.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import bureau_client
from bureau_client import BureauClient, TokenInvalido

scenarios("bureau.feature")

LENTO_S = 0.6        # resposta lenta: passa do timeout de leitura do cliente
TIMEOUT_LEITURA = 0.2


def payload_ok(id_cliente: str) -> dict:
    return {"id_cliente": id_cliente, "score": 700, "restricoes_ativas": 0, "parcelas_outras_instituicoes": 150.0,
            "consultas_90_dias": 1, "meses_historico_bureau": 48}


def resposta(tipo: str, id_cliente: str) -> tuple[int, str]:
    ok = payload_ok(id_cliente)
    corpos = {
        "ok": json.dumps(ok),
        "lista": "[]",
        "nulo": "null",
        "campo_faltando": json.dumps({k: v for k, v in ok.items() if k != "score"}),
        "score_texto": json.dumps({**ok, "score": "abc"}),
        "score_fora_faixa": json.dumps({**ok, "score": 5000}),
        "outro_cliente": json.dumps({**ok, "id_cliente": "C-OUTRO"}),
        "json_quebrado": '{"id_cliente": "' + id_cliente + '", "sco',
    }
    if tipo in corpos:
        return 200, corpos[tipo]
    return int(tipo), json.dumps({"erro": tipo})


class BureauFalso:
    def __init__(self):
        self.roteiros: dict[str, list[str]] = {}
        self.sempre: str | None = None
        self.chamadas = 0
        self._lock = threading.Lock()
        falso = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                id_cliente = self.path.rsplit("/", 1)[-1]
                with falso._lock:
                    falso.chamadas += 1
                    fila = falso.roteiros.get(id_cliente)
                    tipo = fila.pop(0) if fila else (falso.sempre or "404")
                if tipo == "lento":
                    time.sleep(LENTO_S)
                    tipo = "ok"
                status, corpo = resposta(tipo, id_cliente)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(corpo.encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass  # o cliente já desistiu por timeout

            def log_message(self, *a):
                pass

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.servidor.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def fechar(self):
        self.servidor.shutdown()
        self.servidor.server_close()


@pytest.fixture
def ctx():
    return {}


@given("um bureau simulado na rede local", target_fixture="bureau")
def _bureau(monkeypatch):
    b = BureauFalso()
    monkeypatch.setattr(bureau_client, "URL_BASE", b.url)
    yield b
    b.fechar()


def novo_cliente(cache, token="token-de-teste") -> BureauClient:
    return BureauClient(token=token, cache_path=cache, max_tentativas=5, timeout=(1, TIMEOUT_LEITURA),
                        backoff_base=0.001, backoff_max=0.002, workers=8)


@given("um cliente do bureau com timeout curto e no máximo 5 tentativas")
def _cliente(ctx, tmp_path):
    ctx["cache"] = tmp_path / "bureau_cache.jsonl"
    ctx["cli"] = novo_cliente(ctx["cache"])


@given(parsers.parse('que o bureau responde "{roteiro}" para o cliente "{id_cliente}"'))
def _roteiro(bureau, roteiro, id_cliente):
    bureau.roteiros[id_cliente] = [t.strip() for t in roteiro.split(",")]


@given(parsers.parse('que o bureau responde sempre "{tipo}"'))
def _sempre(bureau, tipo):
    bureau.sempre = tipo


@given(parsers.parse('o pipeline já consultou o cliente "{id_cliente}"'))
def _ja_consultou(ctx, id_cliente):
    assert ctx["cli"].consultar(id_cliente)["status"] == "ok"


@given(parsers.parse('um cache com o cliente "{id_cliente}" e uma última linha cortada no meio'))
def _cache_cortado(ctx, id_cliente):
    linha = json.dumps({**payload_ok(id_cliente), "status": "ok", "tentativas": 1})
    ctx["cache"].write_text(linha + "\n" + '{"id_cliente": "C-2", "sta', encoding="utf-8")


def _consultar(ctx, f):
    try:
        ctx["resultado"] = f()
    except TokenInvalido as e:
        ctx["erro"] = e


@when(parsers.parse('o pipeline consulta o cliente "{id_cliente}"'))
def _consulta(ctx, id_cliente):
    _consultar(ctx, lambda: ctx["cli"].consultar(id_cliente))


@when(parsers.parse("o pipeline consulta um lote de {n:d} clientes"))
def _lote(ctx, n):
    _consultar(ctx, lambda: ctx["cli"].consultar_lote([f"C-{i}" for i in range(n)], rodadas=1))


@when(parsers.parse('uma nova execução sem token consulta o cliente "{id_cliente}"'))
def _sem_token(ctx, monkeypatch, id_cliente):
    def sem_token():
        raise TokenInvalido("nenhum token configurado")
    monkeypatch.setattr(bureau_client, "ler_token", sem_token)
    _consultar(ctx, lambda: novo_cliente(ctx["cache"], token=None).consultar(id_cliente))


@then(parsers.parse('os dados do cliente "{id_cliente}" são aceitos com score {score:d}'))
def _aceitos(ctx, id_cliente, score):
    r = ctx["resultado"]
    assert (r["status"], r["id_cliente"], r["score"]) == ("ok", id_cliente, score)


@then(parsers.parse("foram feitas {n:d} chamadas ao bureau"))
def _n_chamadas(bureau, n):
    assert bureau.chamadas == n


@then(parsers.parse("foram feitas menos de {n:d} chamadas ao bureau"))
def _menos_chamadas(bureau, n):
    assert bureau.chamadas < n


@then(parsers.parse("a execução registrou {n:d} timeout"))
def _timeouts(ctx, n):
    assert ctx["cli"].stats.timeouts == n


@then(parsers.parse('o cliente "{id_cliente}" fica sem dados do bureau'))
def _sem_dados(ctx, id_cliente):
    assert (ctx["resultado"]["id_cliente"], ctx["resultado"]["status"]) == (id_cliente, "indisponivel")


@then(parsers.parse('o cliente "{id_cliente}" não vai para o cache'))
def _fora_do_cache(ctx, id_cliente):
    assert not ctx["cache"].exists() or id_cliente not in ctx["cache"].read_text(encoding="utf-8")


@then(parsers.parse('o cliente "{id_cliente}" é registrado como não encontrado'))
def _nao_encontrado(ctx, id_cliente):
    assert (ctx["resultado"]["id_cliente"], ctx["resultado"]["status"]) == (id_cliente, "nao_encontrado")


@then("a execução é interrompida por token inválido")
def _token_invalido(ctx):
    assert isinstance(ctx.get("erro"), TokenInvalido)
