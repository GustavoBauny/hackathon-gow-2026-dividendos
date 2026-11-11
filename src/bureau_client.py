"""Cliente resiliente da API do bureau.

A API falha com 503 e às vezes demora alguns segundos, de propósito. Tratamento:
  * timeout por chamada (conexão + leitura) para não travar em resposta lenta;
  * retry com backoff exponencial + jitter em 503, 5xx, timeout e erro de conexão;
  * 401 aborta na hora (token errado não melhora tentando de novo); 404 é registrado como "sem dados";
  * chamadas em paralelo (não há limite por minuto), para a lentidão não somar;
  * cache em disco (a resposta de um cliente não muda): reexecuções não chamam a API de novo
    e uma execução interrompida continua de onde parou;
  * validação do esquema da resposta e log com estatísticas (tentativas, 503, latência).
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import requests

log = logging.getLogger("bureau")

URL_BASE = os.environ.get("FORTUNA_BUREAU_URL", "https://gowlab-fortuna-bureau.azurewebsites.net")
CAMPOS = {"score": int, "restricoes_ativas": int, "parcelas_outras_instituicoes": float,
          "consultas_90_dias": int, "meses_historico_bureau": int}


class TokenInvalido(RuntimeError):
    pass


def ler_token() -> str:
    """Ordem: variável FORTUNA_BUREAU_TOKEN, arquivo .bureau_token, linha BUREAU:<token> ou
    FORTUNA_BUREAU_TOKEN=<token> no .env. Todos ficam fora do git."""
    tok = os.environ.get("FORTUNA_BUREAU_TOKEN")
    raiz = Path(__file__).resolve().parent.parent
    if not tok and (raiz / ".bureau_token").exists():
        tok = (raiz / ".bureau_token").read_text(encoding="utf-8").strip()
    if not tok and (raiz / ".env").exists():
        for linha in (raiz / ".env").read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            for prefixo in ("BUREAU:", "FORTUNA_BUREAU_TOKEN="):
                if linha.startswith(prefixo):
                    tok = linha[len(prefixo):].strip().strip('"').strip("'")
    if not tok:
        raise TokenInvalido("Defina FORTUNA_BUREAU_TOKEN, crie .bureau_token ou ponha BUREAU:<token> no .env.")
    return tok


@dataclass
class Estatisticas:
    chamadas: int = 0
    sucesso: int = 0
    status_503: int = 0
    timeouts: int = 0
    erros_conexao: int = 0
    nao_encontrado: int = 0
    falha_definitiva: int = 0
    do_cache: int = 0
    latencias: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **kw):
        with self.lock:
            for k, v in kw.items():
                if k == "latencia":
                    self.latencias.append(v)
                else:
                    setattr(self, k, getattr(self, k) + v)

    def resumo(self) -> dict:
        lat = sorted(self.latencias)
        pct = (lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 2)) if lat else (lambda q: None)
        return {"chamadas_http": self.chamadas, "sucesso": self.sucesso, "respostas_503": self.status_503,
                "timeouts": self.timeouts, "erros_conexao": self.erros_conexao, "404": self.nao_encontrado,
                "falha_definitiva": self.falha_definitiva, "lidos_do_cache": self.do_cache,
                "latencia_p50_s": pct(0.5), "latencia_p95_s": pct(0.95), "latencia_max_s": lat[-1] if lat else None}


class BureauClient:
    def __init__(self, token: str | None = None, cache_path: str | Path = "data/bureau_cache.jsonl",
                 max_tentativas: int = 10, timeout=(5, 20), workers: int = 24, backoff_base: float = 0.5,
                 backoff_max: float = 15.0):
        self.token = token  # lido só na primeira chamada à API: com cache completo, roda sem token
        self.cache_path = Path(cache_path)
        self.max_tentativas = max_tentativas
        self.timeout = timeout
        self.workers = workers
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.stats = Estatisticas()
        self._lock_cache = threading.Lock()
        self._local = threading.local()
        self.cache = self._carregar_cache()

    # ---------- cache ----------
    def _carregar_cache(self) -> dict:
        cache = {}
        if self.cache_path.exists():
            for linha in self.cache_path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(linha) if linha.strip() else None
                except json.JSONDecodeError:
                    log.warning("linha incompleta no cache ignorada: %.60s", linha)
                    continue
                if isinstance(r, dict) and "id_cliente" in r:
                    cache[r["id_cliente"]] = r
        return cache

    def _gravar_cache(self, registro: dict):
        with self._lock_cache:
            self.cache[registro["id_cliente"]] = registro
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    # ---------- http ----------
    def _sessao(self) -> requests.Session:
        if not hasattr(self._local, "s"):
            self.token = self.token or ler_token()
            s = requests.Session()
            s.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
            self._local.s = s
        return self._local.s

    def _espera(self, tentativa: int):
        t = min(self.backoff_max, self.backoff_base * 2 ** (tentativa - 1))
        time.sleep(random.uniform(0.5 * t, t))  # jitter: evita todos os threads voltarem juntos

    @staticmethod
    def _validar(payload, id_cliente: str) -> dict:
        if not isinstance(payload, dict):
            raise ValueError(f"resposta não é um objeto: {type(payload).__name__}")
        if payload.get("id_cliente") != id_cliente:
            raise ValueError(f"resposta de outro cliente: {payload.get('id_cliente')} != {id_cliente}")
        reg = {"id_cliente": id_cliente, "status": "ok"}
        for campo, tipo in CAMPOS.items():
            if payload.get(campo) is None:
                raise ValueError(f"campo ausente: {campo}")
            try:
                reg[campo] = tipo(payload[campo])
            except (TypeError, ValueError) as e:
                raise ValueError(f"campo {campo} inválido: {payload[campo]!r}") from e
        if not 0 <= reg["score"] <= 1000 or min(reg[c] for c in CAMPOS if c != "score") < 0:
            raise ValueError(f"valores fora da faixa: {reg}")
        return reg

    def consultar(self, id_cliente: str) -> dict:
        if id_cliente in self.cache:
            self.stats.add(do_cache=1)
            return self.cache[id_cliente]
        url = f"{URL_BASE}/v1/bureau/{id_cliente}"
        ultimo_erro = None
        for tentativa in range(1, self.max_tentativas + 1):
            t0 = time.perf_counter()
            try:
                self.stats.add(chamadas=1)
                r = self._sessao().get(url, timeout=self.timeout)
                self.stats.add(latencia=time.perf_counter() - t0)
            except requests.Timeout as e:
                self.stats.add(timeouts=1)
                ultimo_erro = f"timeout: {e}"
                self._espera(tentativa)
                continue
            except requests.ConnectionError as e:
                self.stats.add(erros_conexao=1)
                ultimo_erro = f"conexao: {e}"
                self._espera(tentativa)
                continue

            if r.status_code == 200:
                try:
                    reg = self._validar(r.json(), id_cliente)
                except (ValueError, json.JSONDecodeError) as e:  # resposta corrompida: tenta de novo
                    ultimo_erro = f"payload inválido: {e}"
                    self._espera(tentativa)
                    continue
                reg["tentativas"] = tentativa
                self.stats.add(sucesso=1)
                self._gravar_cache(reg)
                return reg
            if r.status_code in (401, 403):
                raise TokenInvalido(f"Bureau respondeu {r.status_code}: token ausente, inválido ou sem permissão.")
            if r.status_code == 404:
                self.stats.add(nao_encontrado=1)
                reg = {"id_cliente": id_cliente, "status": "nao_encontrado", "tentativas": tentativa}
                self._gravar_cache(reg)
                return reg
            if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                self.stats.add(falha_definitiva=1)
                log.warning("bureau respondeu %s para %s: não adianta repetir", r.status_code, id_cliente)
                return {"id_cliente": id_cliente, "status": "indisponivel", "erro": f"HTTP {r.status_code}"}
            if r.status_code == 503 or r.status_code >= 500:
                self.stats.add(status_503=1)
                ultimo_erro = f"HTTP {r.status_code}"
                self._espera(tentativa)
                continue
            ultimo_erro = f"HTTP {r.status_code}: {r.text[:200]}"
            self._espera(tentativa)

        self.stats.add(falha_definitiva=1)
        log.warning("bureau falhou para %s após %d tentativas (%s)", id_cliente, self.max_tentativas, ultimo_erro)
        return {"id_cliente": id_cliente, "status": "indisponivel", "erro": ultimo_erro}  # não vai para o cache

    def consultar_lote(self, ids: list[str], rodadas: int = 3) -> list[dict]:
        """Consulta em paralelo; quem falhar em todas as tentativas entra numa nova rodada."""
        resultados: dict[str, dict] = {}
        pendentes = list(dict.fromkeys(ids))
        for rodada in range(1, rodadas + 1):
            if not pendentes:
                break
            log.info("rodada %d: %d clientes", rodada, len(pendentes))
            ex = ThreadPoolExecutor(max_workers=self.workers)
            try:
                futs = {ex.submit(self.consultar, i): i for i in pendentes}
                for n, fut in enumerate(as_completed(futs), 1):
                    reg = fut.result()
                    resultados[reg["id_cliente"]] = reg
                    if n % 250 == 0:
                        log.info("  %d/%d", n, len(pendentes))
            except TokenInvalido:
                ex.shutdown(wait=True, cancel_futures=True)
                raise
            ex.shutdown(wait=True)
            pendentes = [i for i, r in resultados.items() if r["status"] == "indisponivel"]
            if pendentes:
                time.sleep(5)
        return [resultados[i] for i in dict.fromkeys(ids)]
