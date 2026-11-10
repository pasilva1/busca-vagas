# Cliente de buscas

Página em FastAPI que chama a API JobSpy, grava as buscas e permite filtrar e baixar o resultado.

A integração dos dois containers está no [README da raiz](../README.md).

## IP e porta da API

O cliente precisa do endereço publicado pelo container JobSpy.

No `.env`, a partir de `.env.example`:

```text
JOBSPY_HOST=192.168.1.8
JOBSPY_PORT=4000
```

Ou, com os containers no ar, na página `http://IP_DA_MAQUINA:4100`, nos campos **IP ou host** e **Porta**. Salvar na página guarda o endereço e ele passa a valer nas buscas seguintes.

```bash
docker compose up -d --build
```
