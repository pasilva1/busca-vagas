# Integração: API JobSpy e cliente de buscas

Dois containers separados. A API pesquisa as vagas. O cliente grava a busca, filtra o resultado e permite baixar JSON ou CSV.

```text
navegador
    |
    |  http://IP_DA_MAQUINA:4100
    v
container cliente_vagas
    |
    |  http://IP_DA_MAQUINA:4000
    v
container jobspy-api
    |
    v
LinkedIn, Indeed e os outros sites configurados
```

Eles não compartilham rede do Docker. O cliente não enxerga o nome `api` do outro Compose. Por isso o cliente precisa do IP da máquina e da porta publicada da API.

Dentro do container do cliente, `localhost` é o próprio cliente. O endereço da API tem de ser o IP da máquina, por exemplo `192.168.1.8`, ou `host.docker.internal` quando os dois containers estão no mesmo Docker.

## O que cada um faz

| Pasta | Container | Porta | Função |
| --- | --- | --- | --- |
| `JOBSPY` | `jobspy-api-1` | 4000 | Consulta os sites e devolve JSON em `GET /jobs` e `GET /jobs/linkedin` |
| `DOCKER_CLIENTE_VAGAS` | `cliente_vagas` | 4100 | Página para criar, filtrar, atualizar, ler, apagar e baixar as buscas |

A API não guarda as buscas. Cada consulta do cliente chama a API de novo. Atualizar uma busca também chama a API de novo e substitui as vagas gravadas.

## Subir os dois

Na pasta `JOBSPY`:

```bash
docker compose up -d --build
```

A API fica em `http://IP_DA_MAQUINA:4000`. A documentação fica em `/docs` e a saúde em `/health`.

Na pasta `DOCKER_CLIENTE_VAGAS`, copie o exemplo e coloque o IP e a porta da API:

```bash
cp .env.example .env
```

O arquivo `.env` fica assim:

```text
JOBSPY_HOST=192.168.1.8
JOBSPY_PORT=4000
```

`JOBSPY_HOST` é o IP da máquina onde o container da API está publicado. `JOBSPY_PORT` é a porta publicada, em geral `4000`.

Depois:

```bash
docker compose up -d --build
```

A página fica em `http://IP_DA_MAQUINA:4100`.

## Informar IP e porta na página

No alto do formulário existe **Conexão com o JobSpy**. Preencha o IP e a porta e clique em **Salvar IP e porta**. O cliente grava esses valores e passa a usá-los nas próximas buscas.

Esse valor gravado na página permanece depois de reiniciar o container. Ele vale mais do que o `.env`. Para trocar de servidor, altere de novo na página.

O texto abaixo dos campos mostra o endereço chamado, no formato `http://IP:PORTA`. O canto da página mostra se essa API respondeu.

## O que o cliente envia

Uma busca nova chama:

- `GET /jobs` quando há um ou mais sites
- `GET /jobs/linkedin` quando **Somente LinkedIn** está marcado

O local enviado junta cidade, estado e `Brasil`. Remoto **Sim** pede só vagas remotas. Remoto **Não** não restringe a modalidade.

A resposta fica gravada no volume `cliente_vagas_data`. A API JobSpy não recebe essa cópia.

## Conferir a ligação

Na máquina da API:

```bash
curl http://127.0.0.1:4000/health
```

Na página do cliente, o estado precisa aparecer como disponível no endereço que você salvou. Se aparecer indisponível, confira o IP, a porta publicada e se o container `jobspy-api-1` está no ar.

## Parar

```bash
cd JOBSPY && docker compose down
cd DOCKER_CLIENTE_VAGAS && docker compose down
```

`docker compose down` não apaga as buscas gravadas. O volume do cliente continua. `docker compose down -v` na pasta do cliente apaga essas buscas.
