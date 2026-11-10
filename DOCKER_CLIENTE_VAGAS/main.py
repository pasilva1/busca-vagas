import csv
import io
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("DB_PATH", "/data/buscas.db")
HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$"
)
PAGE = Path(__file__).resolve().with_name("index.html")
UPSTREAM_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

SITES = {
    "linkedin",
    "indeed",
    "glassdoor",
    "zip_recruiter",
    "bayt",
    "naukri",
    "bdjobs",
    "hellowork",
}
JOB_TYPES = {
    "fulltime",
    "parttime",
    "contract",
    "temporary",
    "internship",
    "perdiem",
    "other",
    "volunteer",
}
ESTADOS = {
    "Acre",
    "Alagoas",
    "Amapá",
    "Amazonas",
    "Bahia",
    "Ceará",
    "Distrito Federal",
    "Espírito Santo",
    "Goiás",
    "Maranhão",
    "Mato Grosso",
    "Mato Grosso do Sul",
    "Minas Gerais",
    "Pará",
    "Paraíba",
    "Paraná",
    "Pernambuco",
    "Piauí",
    "Rio de Janeiro",
    "Rio Grande do Norte",
    "Rio Grande do Sul",
    "Rondônia",
    "Roraima",
    "Santa Catarina",
    "São Paulo",
    "Sergipe",
    "Tocantins",
}
CSV_FIRST = [
    "site",
    "title",
    "company",
    "location",
    "date_posted",
    "job_type",
    "is_remote",
    "job_url",
    "job_url_direct",
    "min_amount",
    "max_amount",
    "currency",
    "interval",
    "emails",
    "description",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Cliente da API de Busca de Vagas",
    summary="Página para criar, filtrar, atualizar, ler e apagar buscas da API JobSpy.",
    description="""
A página em `/` consulta a API JobSpy. O IP e a porta ficam em **PUT `/conexao`**
ou nas variáveis `JOBSPY_HOST` e `JOBSPY_PORT`.

Cada busca gravada pode ser criada, lida, atualizada e apagada.
Atualizar consulta a API de novo e substitui as vagas daquela busca.
A página filtra a lista de buscas e todos os campos das vagas.
""",
    version="1.1.0",
    lifespan=lifespan,
)


class BuscaIn(BaseModel):
    keywords: str = Field(
        ...,
        min_length=1,
        description="Cargo, profissão ou tecnologia. Exemplo: Python Developer.",
        examples=["Python Developer"],
    )
    location: str = Field(
        "Brasil",
        description="Local enviado à API. Se estado ou cidade vierem preenchidos, este valor é montado de novo.",
    )
    cidade: Optional[str] = Field(
        None,
        description="Cidade. Pode ficar vazia para pesquisar o estado inteiro ou o Brasil.",
    )
    estado: Optional[str] = Field(
        None,
        description="Estado do Brasil. A busca usa Cidade, Estado, Brasil.",
    )
    sites: str = Field(
        "linkedin,indeed",
        description="Sites separados por vírgula. Ignorado quando somente_linkedin é true.",
    )
    results: int = Field(10, ge=1, le=100, description="Máximo pedido por site, de 1 a 100.")
    hours_old: Optional[int] = Field(
        None,
        ge=1,
        description="Somente vagas das últimas N horas. Vazio não envia o filtro.",
    )
    job_type: Optional[str] = Field(
        None,
        description="fulltime, parttime, contract, temporary, internship, perdiem, other ou volunteer.",
    )
    is_remote: bool = Field(False, description="true pede somente vagas remotas.")
    somente_linkedin: bool = Field(
        False,
        description="true chama /jobs/linkedin em vez de /jobs.",
    )


def connect() -> sqlite3.Connection:
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buscas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                criado_em TEXT NOT NULL,
                pedido_json TEXT NOT NULL,
                upstream_path TEXT NOT NULL,
                upstream_status INTEGER,
                ok INTEGER NOT NULL,
                saida_json TEXT,
                erro TEXT
            )
            """
        )
        colunas = {item[1] for item in conn.execute("PRAGMA table_info(buscas)")}
        if "atualizado_em" not in colunas:
            conn.execute("ALTER TABLE buscas ADD COLUMN atualizado_em TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
            """
        )


def endereco_inicial() -> tuple[str, int]:
    host = os.environ.get("JOBSPY_HOST", "").strip()
    porta_texto = os.environ.get("JOBSPY_PORT", "").strip()
    if host or porta_texto:
        try:
            porta = int(porta_texto or "4000")
        except ValueError:
            porta = 4000
        return host or "192.168.1.8", porta
    url = os.environ.get("JOBSPY_API_URL", "").strip()
    if url:
        analisada = urlparse(url if "://" in url else f"http://{url}")
        if analisada.hostname:
            return analisada.hostname, analisada.port or 4000
    return "192.168.1.8", 4000


def validar_host(host: str) -> str:
    texto = host.strip()
    if not HOST_RE.match(texto):
        raise HTTPException(
            status_code=422,
            detail="Informe o IP ou o nome do host, sem http:// e sem barra.",
        )
    return texto


def obter_conexao() -> dict[str, Any]:
    host, porta = endereco_inicial()
    with connect() as conn:
        linhas = {
            row["chave"]: row["valor"]
            for row in conn.execute(
                "SELECT chave, valor FROM config WHERE chave IN ('jobspy_host', 'jobspy_port')"
            )
        }
    if linhas.get("jobspy_host"):
        host = linhas["jobspy_host"]
    if linhas.get("jobspy_port"):
        porta = int(linhas["jobspy_port"])
    return {"host": host, "port": porta, "url": f"http://{host}:{porta}"}


def gravar_conexao(host: str, porta: int) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO config (chave, valor) VALUES ('jobspy_host', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (host,),
        )
        conn.execute(
            """
            INSERT INTO config (chave, valor) VALUES ('jobspy_port', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (str(porta),),
        )
    return obter_conexao()


def jobspy_api_url() -> str:
    return obter_conexao()["url"]


class ConexaoIn(BaseModel):
    host: str = Field(..., description="IP ou nome da máquina onde a API JobSpy está publicada.")
    port: int = Field(..., ge=1, le=65535, description="Porta publicada pelo container JobSpy. O padrão é 4000.")


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def carregar(row: sqlite3.Row) -> dict[str, Any]:
    saida = json.loads(row["saida_json"]) if row["saida_json"] else None
    pedido = json.loads(row["pedido_json"])
    jobs = []
    if isinstance(saida, dict) and isinstance(saida.get("jobs"), list):
        jobs = saida["jobs"]
    chaves = row.keys()
    atualizado_em = row["atualizado_em"] if "atualizado_em" in chaves else None
    return {
        "id": row["id"],
        "criado_em": row["criado_em"],
        "atualizado_em": atualizado_em,
        "ok": bool(row["ok"]),
        "upstream_status": row["upstream_status"],
        "upstream_path": row["upstream_path"],
        "erro": row["erro"],
        "pedido": pedido,
        "quantidade": len(jobs),
        "saida": saida,
        "downloads": {
            "json": f"/buscas/{row['id']}/download?formato=json",
            "csv": f"/buscas/{row['id']}/download?formato=csv",
        },
    }


def resumo(item: dict[str, Any]) -> dict[str, Any]:
    pedido = item["pedido"]
    return {
        "id": item["id"],
        "criado_em": item["criado_em"],
        "atualizado_em": item["atualizado_em"],
        "ok": item["ok"],
        "keywords": pedido.get("keywords"),
        "location": pedido.get("location"),
        "cidade": pedido.get("cidade"),
        "estado": pedido.get("estado"),
        "sites": pedido.get("sites"),
        "results": pedido.get("results"),
        "hours_old": pedido.get("hours_old"),
        "job_type": pedido.get("job_type"),
        "is_remote": pedido.get("is_remote"),
        "somente_linkedin": pedido.get("somente_linkedin"),
        "quantidade": item["quantidade"],
        "erro": item["erro"],
        "pedido": pedido,
        "downloads": item["downloads"],
    }


def passa_filtro(
    item: dict[str, Any],
    q: Optional[str],
    situacao: Optional[str],
    remoto: Optional[bool],
    somente_linkedin: Optional[bool],
) -> bool:
    if situacao == "ok" and not item["ok"]:
        return False
    if situacao == "erro" and item["ok"]:
        return False
    if remoto is not None and bool(item["is_remote"]) != remoto:
        return False
    if somente_linkedin is not None and bool(item["somente_linkedin"]) != somente_linkedin:
        return False
    if q:
        texto = json.dumps(item, ensure_ascii=False).lower()
        if q.lower() not in texto:
            return False
    return True


def buscar_por_id(busca_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM buscas WHERE id = ?", (busca_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Busca não encontrada.")
    return carregar(row)


def estado_limpo(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    texto = valor.strip()
    return texto or None


def local_da_busca(pedido: BuscaIn) -> str:
    estado = estado_limpo(pedido.estado)
    if pedido.cidade is not None:
        cidade = pedido.cidade.strip()
    else:
        cidade = (pedido.location or "").strip()
    if not estado:
        return cidade or "Brasil"
    if cidade.lower() in {"", "brasil", "brazil"}:
        return f"{estado}, Brasil"
    if estado.lower() not in cidade.lower():
        cidade = f"{cidade}, {estado}"
    if "brasil" not in cidade.lower() and "brazil" not in cidade.lower():
        cidade = f"{cidade}, Brasil"
    return cidade


def preparar(pedido: BuscaIn) -> BuscaIn:
    estado = estado_limpo(pedido.estado)
    if estado and estado not in ESTADOS:
        raise HTTPException(status_code=422, detail="Escolha um estado do Brasil ou deixe sem estado.")
    cidade = pedido.cidade.strip() if isinstance(pedido.cidade, str) else pedido.cidade
    ajustado = pedido.model_copy(update={"estado": estado, "cidade": cidade})
    return ajustado.model_copy(update={"location": local_da_busca(ajustado)})


def validar(pedido: BuscaIn) -> list[str]:
    if pedido.job_type and pedido.job_type not in JOB_TYPES:
        raise HTTPException(
            status_code=422,
            detail="job_type inválido. Use fulltime, parttime, contract, temporary, internship, perdiem, other ou volunteer.",
        )
    sites = [parte.strip().lower() for parte in pedido.sites.split(",") if parte.strip()]
    if pedido.somente_linkedin:
        return []
    if not sites:
        raise HTTPException(status_code=422, detail="Informe ao menos um site em sites.")
    if "google" in sites:
        raise HTTPException(
            status_code=422,
            detail="A API de origem não aceita google, porque não expõe google_search_term.",
        )
    desconhecidos = [site for site in sites if site not in SITES]
    if desconhecidos:
        raise HTTPException(
            status_code=422,
            detail=f"Site não suportado: {', '.join(desconhecidos)}.",
        )
    return sites


def montar_chamada(pedido: BuscaIn, sites: list[str]) -> tuple[str, dict[str, Any]]:
    if pedido.somente_linkedin:
        params: dict[str, Any] = {
            "keywords": pedido.keywords,
            "location": pedido.location,
            "results": pedido.results,
            "is_remote": pedido.is_remote,
        }
        if pedido.hours_old is not None:
            params["hours_old"] = pedido.hours_old
        return "/jobs/linkedin", params

    params = {
        "keywords": pedido.keywords,
        "location": pedido.location,
        "sites": ",".join(sites),
        "results": pedido.results,
        "is_remote": pedido.is_remote,
    }
    if pedido.hours_old is not None:
        params["hours_old"] = pedido.hours_old
    if pedido.job_type:
        params["job_type"] = pedido.job_type
    return "/jobs", params


def consulta_de(params: dict[str, Any]) -> str:
    limpo = {}
    for chave, valor in params.items():
        if isinstance(valor, bool):
            limpo[chave] = "true" if valor else "false"
        else:
            limpo[chave] = valor
    return urlencode(limpo)


def gravar(
    pedido: BuscaIn,
    path: str,
    status_code: Optional[int],
    ok: bool,
    saida: Any,
    erro: Optional[str],
) -> int:
    momento = agora()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO buscas (
                criado_em, atualizado_em, pedido_json, upstream_path, upstream_status, ok, saida_json, erro
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                momento,
                momento,
                pedido.model_dump_json(),
                path,
                status_code,
                1 if ok else 0,
                json.dumps(saida, ensure_ascii=False) if saida is not None else None,
                erro,
            ),
        )
        return int(cursor.lastrowid)


def substituir(
    busca_id: int,
    pedido: BuscaIn,
    path: str,
    status_code: Optional[int],
    ok: bool,
    saida: Any,
    erro: Optional[str],
) -> None:
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE buscas
               SET atualizado_em = ?, pedido_json = ?, upstream_path = ?, upstream_status = ?,
                   ok = ?, saida_json = ?, erro = ?
             WHERE id = ?
            """,
            (
                agora(),
                pedido.model_dump_json(),
                path,
                status_code,
                1 if ok else 0,
                json.dumps(saida, ensure_ascii=False) if saida is not None else None,
                erro,
                busca_id,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Busca não encontrada.")


async def consultar(path: str, params: dict[str, Any]) -> tuple[int, Any, Optional[str]]:
    base = jobspy_api_url()
    url = f"{base}{path}"
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            resposta = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível falar com a API de vagas em {base}: {exc}",
        ) from exc

    try:
        corpo = resposta.json()
    except json.JSONDecodeError:
        corpo = {"detail": resposta.text[:4000]}

    if resposta.status_code >= 400:
        detalhe = corpo.get("detail") if isinstance(corpo, dict) else corpo
        return resposta.status_code, corpo, f"A API de vagas respondeu {resposta.status_code}: {detalhe}"
    return resposta.status_code, corpo, None


async def executar(pedido: BuscaIn) -> tuple[BuscaIn, str, int, Any, Optional[str]]:
    pedido = preparar(pedido)
    sites = validar(pedido)
    path, params = montar_chamada(pedido, sites)
    status_code, corpo, erro = await consultar(path, params)
    return pedido, f"{path}?{consulta_de(params)}", status_code, corpo, erro


def resposta_de_busca(item: dict[str, Any], erro: Optional[str]) -> dict[str, Any]:
    if erro:
        item["aviso"] = erro
    return item


@app.get("/", include_in_schema=False)
def pagina():
    if not PAGE.is_file():
        raise HTTPException(status_code=500, detail="A página HTML não está no container.")
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/health", tags=["Status"], summary="Saúde deste serviço")
def health():
    return {"status": "ok", "timestamp": agora(), "jobspy_api": jobspy_api_url()}


@app.get("/conexao", tags=["Status"], summary="Ler IP e porta da API JobSpy")
def ler_conexao():
    return obter_conexao()


@app.put("/conexao", tags=["Status"], summary="Gravar IP e porta da API JobSpy")
def atualizar_conexao(pedido: ConexaoIn):
    return gravar_conexao(validar_host(pedido.host), pedido.port)


@app.get("/jobspy/health", tags=["Status"], summary="Saúde da API de vagas")
async def jobspy_health():
    status_code, corpo, erro = await consultar("/health", {})
    return {"jobspy_api": jobspy_api_url(), "ok": erro is None, "status_code": status_code, "saida": corpo}


@app.get("/buscas", tags=["Buscas"], summary="Listar buscas gravadas")
def listar_buscas(
    q: Optional[str] = Query(None, description="Texto procurado em qualquer campo da busca."),
    situacao: Optional[str] = Query(None, pattern="^(ok|erro)$", description="ok ou erro."),
    remoto: Optional[bool] = Query(None, description="Filtra pelo pedido de vaga remota."),
    somente_linkedin: Optional[bool] = Query(None, description="Filtra buscas só do LinkedIn."),
):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM buscas ORDER BY id DESC").fetchall()
    itens = [
        item
        for item in (resumo(carregar(row)) for row in rows)
        if passa_filtro(item, q, situacao, remoto, somente_linkedin)
    ]
    return {"count": len(itens), "buscas": itens}


@app.get("/buscas/{busca_id}", tags=["Buscas"], summary="Ler a saída gravada de uma busca")
def ler_busca(busca_id: int):
    return buscar_por_id(busca_id)


@app.post("/buscas", tags=["Buscas"], summary="Criar uma busca e ler a saída da API")
async def inserir_busca(pedido: BuscaIn):
    pedido, caminho, status_code, corpo, erro = await executar(pedido)
    busca_id = gravar(pedido, caminho, status_code, erro is None, corpo, erro)
    return resposta_de_busca(buscar_por_id(busca_id), erro)


@app.put("/buscas/{busca_id}", tags=["Buscas"], summary="Atualizar a busca e substituir as vagas")
async def atualizar_busca(busca_id: int, pedido: BuscaIn):
    buscar_por_id(busca_id)
    pedido, caminho, status_code, corpo, erro = await executar(pedido)
    substituir(busca_id, pedido, caminho, status_code, erro is None, corpo, erro)
    return resposta_de_busca(buscar_por_id(busca_id), erro)


@app.delete("/buscas/{busca_id}", tags=["Buscas"], status_code=204, summary="Apagar uma busca gravada")
def excluir_busca(busca_id: int):
    with connect() as conn:
        cursor = conn.execute("DELETE FROM buscas WHERE id = ?", (busca_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Busca não encontrada.")
    return Response(status_code=204)


def valor_csv(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    return str(valor)


def colunas_de(jobs: list[Any]) -> list[str]:
    colunas: list[str] = []
    vistas = set()
    for nome in CSV_FIRST:
        colunas.append(nome)
        vistas.add(nome)
    extras = set()
    for vaga in jobs:
        if isinstance(vaga, dict):
            extras.update(chave for chave in vaga.keys() if chave not in vistas)
    colunas.extend(sorted(extras))
    return colunas


@app.get("/buscas/{busca_id}/download", tags=["Buscas"], summary="Baixar a saída em JSON ou CSV")
def baixar_busca(
    busca_id: int,
    formato: str = Query("json", pattern="^(json|csv)$", description="json devolve a saída da API. csv devolve as vagas."),
):
    item = buscar_por_id(busca_id)
    saida = item["saida"] if item["saida"] is not None else {"erro": item["erro"]}

    if formato == "json":
        conteudo = json.dumps(saida, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=conteudo,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="busca-{busca_id}.json"'},
        )

    jobs = saida.get("jobs") if isinstance(saida, dict) else None
    if not isinstance(jobs, list):
        raise HTTPException(status_code=409, detail="Esta busca não tem uma lista de vagas para exportar em CSV.")

    colunas = colunas_de(jobs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=colunas, extrasaction="ignore")
    writer.writeheader()
    for vaga in jobs:
        if not isinstance(vaga, dict):
            continue
        writer.writerow({coluna: valor_csv(vaga.get(coluna)) for coluna in colunas})

    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="busca-{busca_id}.csv"'},
    )
