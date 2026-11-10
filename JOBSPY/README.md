# API de Busca de Vagas

API em FastAPI para pesquisar vagas públicas no LinkedIn e em outros sites de emprego com a biblioteca `python-jobspy`.

## Instalação e inicialização (Windows)

No PowerShell, na pasta do projeto, crie o ambiente virtual e instale as dependências:

```bash
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Inicie o servidor na porta 4000:

```powershell
.\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 4000
```

Abra a documentação interativa, em português, em [http://127.0.0.1:4000/docs](http://127.0.0.1:4000/docs). Nela, expanda um endpoint, clique em **Try it out**, preencha os parâmetros e clique em **Execute** para ver a resposta.

Para parar o servidor, volte ao terminal onde ele está rodando e pressione `Ctrl+C`.

## Executar com Docker Compose (Ubuntu 24.04)

Instale o Docker Engine e o plugin Docker Compose seguindo a
[documentação oficial para Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
Na pasta do projeto (onde está `compose.yaml`), execute:

```bash
docker compose up -d --build
```

O Compose constrói a imagem e inicia a API em segundo plano. A aplicação fica
disponível na porta **4000** do Ubuntu:

- Swagger: [http://localhost:4000/docs](http://localhost:4000/docs)
- Verificação de saúde: [http://localhost:4000/health](http://localhost:4000/health)

Comandos úteis:

```bash
docker compose ps                 # Ver estado e health check
docker compose logs -f api        # Acompanhar os logs
docker compose restart api        # Reiniciar a API
docker compose down               # Parar e remover o contêiner
```

O contêiner executa a API sem modo `--reload` e reinicia automaticamente após
uma falha ou reinicialização do Docker. A porta publicada e a porta interna
são `4000`. Se for acessar de outro computador, use
`http://IP_DO_SERVIDOR:4000/docs` e libere a porta 4000 no firewall conforme
a política da sua rede.

## Integração com o cliente de buscas

O container `DOCKER_CLIENTE_VAGAS` chama esta API. Ele precisa do IP desta
máquina e da porta `4000`. Os dois Compose não compartilham rede, então o
cliente não deve usar `localhost` para chegar aqui. O passo a passo está no
[README de integração](../README.md).

## O que a API faz

- `GET /jobs`: pesquisa em vários sites. Por padrão, usa LinkedIn e Indeed.
- `GET /jobs/linkedin`: pesquisa exclusivamente no LinkedIn.
- `GET /health`: informa se a API está ativa.

As pesquisas dependem da disponibilidade e das regras de acesso das fontes. A API consulta vagas públicas; não faz login nem candidatura. Para evitar excesso de consultas, faça buscas com moderação.

## Exemplos de uso

### Vagas em vários sites

Pesquise vagas de desenvolvedor Python em São Paulo, no Brasil, no LinkedIn e Indeed:

```text
http://127.0.0.1:4000/jobs?keywords=Python%20Developer&location=Sao%20Paulo%2C%20Brasil&sites=linkedin%2Cindeed&results=10
```

### Vagas somente no LinkedIn

Pesquise vagas remotas de Data Engineer publicadas nas últimas 72 horas:

```text
http://127.0.0.1:4000/jobs/linkedin?keywords=Data%20Engineer&location=Sao%20Paulo%2C%20Brasil&is_remote=true&hours_old=72&results=10
```

### Parâmetros

| Parâmetro | Obrigatório | Padrão | Descrição |
|---|---:|---|---|
| `keywords` | Sim | — | Cargo, profissão ou tecnologia, por exemplo `Python Developer`. |
| `location` | Não | `Brasil` | Cidade, estado, país ou `Remoto`. |
| `sites` | Não | `linkedin,indeed` | Sites separados por vírgula; usado por `/jobs`. |
| `results` | Não | `20` em `/jobs`; `25` no LinkedIn | Máximo de resultados solicitado, de 1 a 100. |
| `hours_old` | Não | Sem filtro em `/jobs`; `168` no LinkedIn | Busca vagas publicadas nas últimas N horas. `168` equivale a cerca de 7 dias. |
| `job_type` | Não | Sem filtro | Tipo de vínculo: `fulltime`, `parttime`, `contract`, `temporary`, `internship`, `perdiem`, `other` ou `volunteer`; usado por `/jobs`. O suporte depende do site. |
| `is_remote` | Não | `false` | Use `true` para solicitar somente vagas remotas. |

### Entendendo a resposta

A API retorna JSON. Por exemplo, `/jobs` pode retornar:

```json
{
  "count": 1,
  "search": {
    "keywords": "Python Developer",
    "location": "Sao Paulo",
    "sites": ["linkedin", "indeed"],
    "results_wanted": 10
  },
  "jobs": [
    {
      "title": "Desenvolvedor(a) Python",
      "company": "Empresa Exemplo",
      "location": "São Paulo, SP",
      "job_url": "https://www.linkedin.com/jobs/view/1234567890",
      "description": "Descrição da vaga...",
      "job_type": "fulltime",
      "date_posted": "2026-01-15",
      "is_remote": false
    }
  ]
}
```

Os campos dentro de cada vaga podem variar conforme a fonte; valores ausentes podem aparecer como `null`. `count` informa quantas vagas foram encontradas. Se nenhuma corresponder aos filtros, `jobs` será uma lista vazia.

## Entendendo o `python-jobspy`

O JobSpy é a biblioteca Python que faz as consultas às fontes. A função usada
pela aplicação, `scrape_jobs()`, consulta os sites escolhidos e retorna uma
tabela Pandas; a API transforma essa tabela em JSON. Os resultados vêm de cada
site individualmente, podem ter campos diferentes e o mesmo anúncio pode
aparecer em mais de uma fonte.

### Fontes

A versão da biblioteca instalada reconhece estes nomes para `sites`:
`linkedin`, `indeed`, `glassdoor`, `zip_recruiter`, `google`, `bayt`,
`naukri`, `bdjobs` e `hellowork`. A API usa LinkedIn e Indeed por padrão.
Cada fonte pode oferecer filtros, campos e precisão de data diferentes.

**Limitação importante:** a biblioteca tem suporte a Google Jobs, mas exige
`google_search_term` para filtrar resultados do Google. Esse parâmetro não é
exposto nesta API; por isso, não inclua `google` em `sites`.

### O que os filtros significam na biblioteca

- `results` (`results_wanted` na biblioteca) é a quantidade solicitada **por
  site**. Por exemplo, dois sites com `results=10` podem retornar até 20
  resultados no total; o número real depende das fontes.
- `hours_old` filtra pela idade da vaga em horas. A precisão depende do site;
  o JobSpy documenta que o Glassdoor arredonda o filtro para dias inteiros.
- `job_type` aceita `fulltime`, `parttime`, `contract`, `temporary`,
  `internship`, `perdiem`, `other` e `volunteer`. Nem todos os sites aceitam
  todos os tipos e alguns podem ignorar filtros não suportados.
- `is_remote` solicita uma busca por vagas remotas, mas a classificação e a
  disponibilidade do filtro dependem da fonte.
- Em `/jobs`, Indeed e Glassdoor usam o mercado Brasil se `location` contiver
  `Brasil` ou `Brazil`; nos demais casos, usam o mercado EUA. Envie, por
  exemplo, `São Paulo, Brasil` para pesquisar vagas locais nesses sites.
- As descrições usam Markdown por padrão. Esta API não ativa `fetch_description`;
  por isso, algumas fontes podem não fornecer uma descrição completa.
- A distância não pode ser ajustada pela API; o JobSpy usa o padrão de 50
  milhas quando aplicável.

### Campos dos resultados

Além dos campos básicos do exemplo, o modelo de vaga do JobSpy pode incluir:

`id`, `site`, `job_url_direct`, `salary_source`, `interval`, `min_amount`,
`max_amount`, `currency`, `job_level`, `job_function`, `listing_type`,
`emails`, `company_industry`, `company_url`, `company_logo`,
`company_url_direct`, `company_addresses`, `company_num_employees`,
`company_revenue`, `company_description`, `skills`, `experience_range`,
`company_rating`, `company_reviews_count`, `vacancy_count` e
`work_from_home_type`.

Esses campos não são garantidos para todas as vagas. Por exemplo, os dados de
salário podem estar ausentes; quando existem, `min_amount` e `max_amount`
representam os valores mínimo e máximo, `currency` a moeda e `interval` o
período de referência. `job_url` é o endereço do anúncio e
`job_url_direct`, quando disponível, é o link direto da candidatura. Campos
sem dados aparecem como `null`.

### Opções da biblioteca que esta API não expõe

A função `scrape_jobs()` também aceita outras opções, como `distance`,
`offset`, `description_format`, `fetch_description`, `easy_apply`,
`linkedin_company_ids`, `google_search_term`, proxies e User-Agent. Elas não
podem ser configuradas pelos endpoints desta aplicação. O comportamento padrão
inclui descrições em Markdown, não buscar descrições extras e distância de 50
milhas quando aplicável.

Consulte a [documentação oficial do JobSpy](https://github.com/speedyapply/JobSpy)
para a lista mais atualizada de fontes, parâmetros e limitações.
