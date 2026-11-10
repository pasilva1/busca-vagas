from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from jobspy import scrape_jobs
from typing import Optional, List
import pandas as pd
from datetime import datetime

app = FastAPI(
    title="API de Busca de Vagas",
    summary="Pesquise vagas públicas no LinkedIn e em outros sites de emprego.",
    description="""
## Sobre esta API

Esta API pesquisa vagas públicas usando a biblioteca
[`python-jobspy`](https://github.com/speedyapply/JobSpy). Você pode pesquisar
em vários sites ao mesmo tempo ou somente no LinkedIn.

## Como começar

1. Escolha um endpoint abaixo.
2. Clique em **Try it out**.
3. Preencha `keywords` com o cargo ou as tecnologias desejadas.
4. Ajuste os filtros, se necessário, e clique em **Execute**.
5. Consulte o código HTTP e o JSON retornado na seção **Responses**.

`keywords` é o único parâmetro obrigatório. Os demais têm valores padrão.
Os resultados dependem da disponibilidade e das regras de acesso dos sites
pesquisados; a API não realiza login nem candidatura a vagas.

## Endpoints

- **GET `/jobs`**: pesquisa em um ou mais sites, como LinkedIn e Indeed.
- **GET `/jobs/linkedin`**: pesquisa exclusivamente no LinkedIn.
- **GET `/health`**: verifica se a API está ativa.

## Como o `python-jobspy` é usado

`python-jobspy` consulta sites de vagas e devolve os resultados como uma tabela
Pandas. Esta API transforma essa tabela em JSON. Ela não é um wrapper de todos
os recursos da biblioteca: cada endpoint expõe somente os parâmetros listados
na própria operação do Swagger.

### Sites disponíveis na biblioteca instalada

Os identificadores reconhecidos pelo `python-jobspy` são `linkedin`,
`indeed`, `glassdoor`, `zip_recruiter`, `google`, `bayt`, `naukri`, `bdjobs`
e `hellowork`. A rota `/jobs` usa LinkedIn e Indeed por padrão. O suporte e os
filtros variam por site. Embora `google` exista na biblioteca, esta API não
expõe `google_search_term`, necessário para filtrar resultados do Google Jobs;
por isso, use as outras fontes nesta API.

### O que acontece durante uma busca

1. A API recebe os filtros da URL.
2. Chama `jobspy.scrape_jobs()` com os sites, termos e filtros aceitos pela rota.
3. O JobSpy consulta as fontes selecionadas e retorna uma tabela Pandas.
4. A API converte as linhas da tabela em uma lista JSON e troca valores
   ausentes (`NaN`) por `null`.

Uma busca em vários sites não é uma busca unificada pelo próprio JobSpy: cada
fonte pode retornar quantidades, campos, datas e interpretações de filtros
diferentes. `site` ajuda a identificar de onde veio cada resultado. O mesmo
anúncio pode aparecer em mais de uma fonte.

### Como ler os filtros

- `results` é o máximo solicitado **para cada site**, não para a pesquisa toda.
  Com dois sites e `results=10`, podem ser retornadas até 20 vagas; não há
  garantia de que todos os sites entreguem esse total.
- `hours_old` representa um período em horas. O cálculo e a precisão dependem
  da fonte; o JobSpy documenta que o Glassdoor filtra por dias inteiros.
- `job_type` aceita `fulltime`, `parttime`, `contract`, `temporary`,
  `internship`, `perdiem`, `other` e `volunteer`. Nem todo site oferece todos
  esses filtros; uma fonte pode ignorar um filtro que não suporta.
- `is_remote` solicita o filtro remoto, mas a classificação e o suporte também
  dependem da fonte.
- Em `/jobs`, Indeed e Glassdoor usam o mercado Brasil quando `location`
  contém `Brasil` ou `Brazil`; nos demais casos, usam o mercado dos EUA. O
  texto de `location` ainda é encaminhado como localização da pesquisa.
- As descrições usam o formato padrão Markdown do JobSpy. A opção
  `fetch_description` não é ativada pela API; algumas fontes podem, portanto,
  retornar descrições ausentes ou resumidas.
- A distância não pode ser configurada nesta API. A biblioteca recebe seu
  padrão de 50 milhas quando esse filtro é usado pela fonte.

### Campos que podem vir em cada vaga

Dependendo do site e dos dados disponíveis, um resultado pode conter:

`id`, `site`, `job_url`, `job_url_direct`, `title`, `company`, `location`,
`date_posted`, `job_type`, `salary_source`, `interval`, `min_amount`,
`max_amount`, `currency`, `is_remote`, `job_level`, `job_function`,
`listing_type`, `emails`, `description`, `company_industry`, `company_url`,
`company_logo`, `company_url_direct`, `company_addresses`,
`company_num_employees`, `company_revenue`, `company_description`, `skills`,
`experience_range`, `company_rating`, `company_reviews_count`,
`vacancy_count` e `work_from_home_type`.

Os campos são opcionais na prática: alguns sites não os fornecem, e a API
converte valores ausentes em `null`. `job_url` normalmente é o link da vaga;
`job_url_direct`, quando disponível, é o link direto para a candidatura.
Valores salariais usam `min_amount`, `max_amount`, `currency` e `interval`;
não presuma que todas as vagas informem salário.

### Recursos da biblioteca não expostos nesta API

O `python-jobspy` também oferece opções como distância, paginação por `offset`,
descrições em HTML ou texto simples, busca de descrições completas, filtro
Easy Apply, busca por IDs de empresas no LinkedIn, `google_search_term`,
proxies e configuração do User-Agent. Esta API não recebe esses parâmetros;
os valores padrão da biblioteca são usados quando não passados (`distance=50`,
`description_format=markdown`, `fetch_description=false`, entre outros).
Consulte a
[documentação oficial do JobSpy](https://github.com/speedyapply/JobSpy) para a
lista atualizada de opções e limitações de cada fonte.

Para exemplos completos de parâmetros e respostas, expanda cada endpoint.
""",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Busca de vagas",
            "description": "Pesquisa vagas em um ou mais sites de emprego.",
        },
        {
            "name": "LinkedIn",
            "description": "Pesquisa vagas públicas exclusivamente no LinkedIn.",
        },
        {
            "name": "Status",
            "description": "Verificação de disponibilidade da API.",
        },
    ],
)

@app.get(
    "/",
    summary="Apresentação da API",
    description="Retorna uma mensagem de boas-vindas e os principais caminhos da API.",
    tags=["Status"],
)
def root():
    return {
        "message": "API de Busca de Vagas",
        "docs": "/docs",
        "endpoints": ["/jobs", "/jobs/linkedin"]
    }

@app.get(
    "/jobs",
    summary="Buscar vagas em vários sites",
    description="""
Pesquisa vagas em um ou mais sites de emprego. Por padrão, consulta LinkedIn
e Indeed. Use `sites` para escolher outras fontes suportadas, separando os
nomes por vírgula.

`results` limita o número solicitado em **cada fonte**, então a quantidade
total pode ser maior que esse valor. A biblioteca reconhece `linkedin`,
`indeed`, `glassdoor`, `zip_recruiter`, `google`, `bayt`, `naukri`, `bdjobs`
e `hellowork`, mas cada site pode oferecer filtros e campos diferentes.
Embora a biblioteca tenha suporte a Google Jobs, esta API não recebe
`google_search_term`; portanto, não selecione `google` nesta rota.

Para Indeed e Glassdoor, o mercado de busca é definido automaticamente:
`Brasil` se `location` contiver `Brasil` ou `Brazil`, caso contrário EUA.
Isso não altera o texto de localização enviado às fontes. Os demais sites
podem interpretar localização e filtros de maneira própria.

### Exemplo

Pesquise até 10 vagas de Python em São Paulo no Brasil, no LinkedIn e no Indeed:

`/jobs?keywords=Python%20Developer&location=Sao%20Paulo%2C%20Brasil&sites=linkedin%2Cindeed&results=10`

Ao pesquisar no Indeed ou Glassdoor no Brasil, indique explicitamente
`location=Brasil`, por exemplo:

`/jobs?keywords=Python&location=Brasil&sites=indeed&results=10`

### Resposta

O campo `count` informa quantas vagas foram encontradas; `jobs` contém os
detalhes retornados pelas fontes. A lista pode estar vazia. Os campos
disponíveis em cada vaga podem variar de acordo com o site. Campos sem valor
são apresentados como `null`; informações salariais, descrição completa,
empresa e modalidade remota não são garantidas.

Campos comuns incluem `site` (fonte), `title` (cargo), `company` (empresa),
`location` (localização), `job_url` (página da vaga), `job_url_direct`
(link direto, se disponível), `date_posted`, `job_type`, `is_remote`,
`description`, `min_amount`, `max_amount`, `currency` e `interval`.
""",
    response_description="Quantidade encontrada, filtros aplicados e lista de vagas.",
    responses={
        200: {
            "description": "Busca concluída. A lista pode estar vazia se nenhuma vaga corresponder aos filtros.",
            "content": {
                "application/json": {
                    "example": {
                        "count": 1,
                        "search": {
                            "keywords": "Python Developer",
                            "location": "Sao Paulo",
                            "sites": ["linkedin", "indeed"],
                            "results_wanted": 10,
                        },
                        "jobs": [
                            {
                                "title": "Desenvolvedor(a) Python",
                                "company": "Empresa Exemplo",
                                "location": "São Paulo, SP",
                                "job_url": "https://www.linkedin.com/jobs/view/1234567890",
                                "description": "Exemplo de descrição da vaga.",
                                "job_type": "fulltime",
                                "date_posted": "2026-01-15",
                                "is_remote": False,
                            }
                        ],
                    }
                }
            },
        },
        500: {
            "description": "Ocorreu um erro durante a consulta a um ou mais sites.",
            "content": {
                "application/json": {
                    "example": {"detail": "Erro ao buscar vagas: descrição do erro"}
                }
            },
        },
    },
    tags=["Busca de vagas"],
)
def search_jobs(
    keywords: str = Query(
        ...,
        description="Cargo, profissão ou tecnologia para pesquisar. Exemplos: `Python Developer`, `Data Engineer`, `Product Manager`.",
        examples={
            "cargo_e_tecnologia": {
                "summary": "Cargo com tecnologia",
                "value": "Python Developer",
            }
        },
    ),
    location: str = Query(
        "Brasil",
        description="Cidade, estado, país ou indicação de trabalho remoto. Exemplos: `São Paulo`, `Brasil`, `Remoto`.",
        examples={
            "sao_paulo": {"summary": "Cidade", "value": "São Paulo"},
            "remoto": {"summary": "Vagas remotas", "value": "Remoto"},
        },
    ),
    sites: Optional[str] = Query(
        "linkedin,indeed",
        description="Sites separados por vírgula. Exemplos: `linkedin`, `linkedin,indeed`. Fontes disponíveis dependem do suporte da biblioteca JobSpy.",
        examples={
            "linkedin_e_indeed": {
                "summary": "LinkedIn e Indeed",
                "value": "linkedin,indeed",
            }
        },
    ),
    results: int = Query(
        20,
        ge=1,
        le=100,
        description="Quantidade máxima de resultados solicitada por site. Aceita valores de 1 a 100.",
        examples={"dez_vagas": {"summary": "Até 10 resultados por site", "value": 10}},
    ),
    hours_old: Optional[int] = Query(
        None,
        description="Filtra vagas publicadas nas últimas N horas. Por exemplo, `72` considera aproximadamente os últimos 3 dias. Se omitido, não é aplicado esse filtro.",
        examples={"ultimas_72_horas": {"summary": "Últimos 3 dias", "value": 72}},
    ),
    job_type: Optional[str] = Query(
        None,
        description="Tipo de vínculo: `fulltime`, `parttime`, `contract`, `temporary`, `internship`, `perdiem`, `other` ou `volunteer`. Nem todas as fontes suportam todos os tipos e algumas podem ignorar o filtro.",
        examples={
            "tempo_integral": {"summary": "Tempo integral", "value": "fulltime"},
            "estagio": {"summary": "Estágio", "value": "internship"},
        },
    ),
    is_remote: bool = Query(
        False,
        description="Quando `true`, solicita somente vagas remotas. Quando `false`, não restringe a pesquisa por modalidade.",
        examples={"somente_remotas": {"summary": "Filtrar vagas remotas", "value": True}},
    ),
):
    """
    Busca vagas nos sites informados, incluindo LinkedIn e Indeed por padrão.
    """
    try:
        site_list = [s.strip() for s in sites.split(",") if s.strip()]
        
        jobs = scrape_jobs(
            site_name=site_list,
            search_term=keywords,
            location=location,
            results_wanted=results,
            hours_old=hours_old,
            job_type=job_type,
            is_remote=is_remote,
            country_indeed="Brazil" if "brasil" in location.lower() or "brazil" in location.lower() else "USA"
        )
        
        if jobs is None or jobs.empty:
            return {"count": 0, "jobs": [], "message": "Nenhuma vaga encontrada"}
        
        # Converter para lista de dicionários
        jobs_list = jobs.to_dict(orient="records")
        
        # Limpar valores NaN
        for job in jobs_list:
            for key, value in job.items():
                if pd.isna(value):
                    job[key] = None
        
        return {
            "count": len(jobs_list),
            "search": {
                "keywords": keywords,
                "location": location,
                "sites": site_list,
                "results_wanted": results
            },
            "jobs": jobs_list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar vagas: {str(e)}")

@app.get(
    "/jobs/linkedin",
    summary="Buscar vagas somente no LinkedIn",
    description="""
Pesquisa vagas públicas exclusivamente no LinkedIn.

### Exemplo

Pesquise vagas de Data Engineer em São Paulo no Brasil, publicadas nas últimas 72 horas:

`/jobs/linkedin?keywords=Data%20Engineer&location=Sao%20Paulo%2C%20Brasil&results=10&hours_old=72`

Para pesquisar vagas remotas, defina `is_remote` como `true`. Por padrão,
esta rota considera vagas das últimas 168 horas (7 dias).

### Resposta

`count` indica a quantidade encontrada, `source` identifica a fonte da busca
e `jobs` contém os detalhes das vagas. Os campos disponíveis podem variar.
""",
    response_description="Quantidade encontrada, fonte da busca e lista de vagas.",
    responses={
        200: {
            "description": "Busca concluída. A lista pode estar vazia se nenhuma vaga corresponder aos filtros.",
            "content": {
                "application/json": {
                    "example": {
                        "count": 1,
                        "source": "linkedin",
                        "jobs": [
                            {
                                "title": "Data Engineer",
                                "company": "Empresa Exemplo",
                                "location": "São Paulo, SP",
                                "job_url": "https://www.linkedin.com/jobs/view/1234567890",
                                "description": "Exemplo de descrição da vaga.",
                                "job_type": "fulltime",
                                "date_posted": "2026-01-15",
                                "is_remote": True,
                            }
                        ],
                    }
                }
            },
        },
        500: {
            "description": "Ocorreu um erro durante a consulta ao LinkedIn.",
            "content": {
                "application/json": {
                    "example": {"detail": "Descrição do erro"}
                }
            },
        },
    },
    tags=["LinkedIn"],
)
def search_linkedin_only(
    keywords: str = Query(
        ...,
        description="Cargo, profissão ou tecnologia para pesquisar. Exemplos: `Data Engineer`, `Python Developer`.",
        examples={
            "data_engineer": {
                "summary": "Pesquisar vagas de engenharia de dados",
                "value": "Data Engineer",
            }
        },
    ),
    location: str = Query(
        "Brasil",
        description="Cidade, estado, país ou indicação de trabalho remoto. Exemplos: `São Paulo`, `Brasil`, `Remoto`.",
        examples={
            "sao_paulo": {"summary": "Cidade", "value": "São Paulo"},
            "remoto": {"summary": "Vagas remotas", "value": "Remoto"},
        },
    ),
    results: int = Query(
        25,
        ge=1,
        le=100,
        description="Quantidade máxima de resultados solicitada. Aceita valores de 1 a 100.",
        examples={"dez_vagas": {"summary": "Até 10 resultados", "value": 10}},
    ),
    hours_old: Optional[int] = Query(
        168,
        description="Filtra vagas publicadas nas últimas N horas. O padrão `168` equivale a aproximadamente 7 dias. Aumente esse valor para pesquisar um período maior.",
        examples={
            "ultimas_72_horas": {"summary": "Últimos 3 dias", "value": 72},
            "padrao_sete_dias": {"summary": "Últimos 7 dias (padrão)", "value": 168},
        },
    ),
    is_remote: bool = Query(
        False,
        description="Quando `true`, solicita somente vagas remotas. Quando `false`, não restringe a pesquisa por modalidade.",
        examples={"somente_remotas": {"summary": "Filtrar vagas remotas", "value": True}},
    ),
):
    """
    Busca vagas públicas exclusivamente no LinkedIn.
    """
    try:
        jobs = scrape_jobs(
            site_name=["linkedin"],
            search_term=keywords,
            location=location,
            results_wanted=results,
            hours_old=hours_old,
            is_remote=is_remote
        )
        
        if jobs is None or jobs.empty:
            return {"count": 0, "jobs": []}
        
        jobs_list = jobs.to_dict(orient="records")
        
        for job in jobs_list:
            for key, value in job.items():
                if pd.isna(value):
                    job[key] = None
        
        return {
            "count": len(jobs_list),
            "source": "linkedin",
            "jobs": jobs_list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get(
    "/health",
    summary="Verificar disponibilidade da API",
    description="Retorna o estado da API e o horário da verificação em UTC.",
    response_description="Estado atual e horário da verificação.",
    tags=["Status"],
)
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
