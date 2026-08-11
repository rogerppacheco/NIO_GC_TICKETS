# NIO GC Tickets

Sistema de **tickets de demandas de parceiros NIO** — substitui o Google Forms + planilha de acompanhamento.

## O que tem

- Cadastro de parceiros (PDV)
- Abertura de demandas (portal parceiro + área interna)
- Fila / tratamento / resposta no site
- Thread de mensagens + anexos
- Máscaras padrão para encaminhar (ex.: Grupo Elite) com botão copiar
- Protocolo `AAAA-NNNN` (igual à planilha)
- Schema Postgres isolado: `nio_gc_tickets` (mesmo banco Railway)

## Melhorias vs Forms

- Vários pedidos no mesmo ticket
- Contato do solicitante
- Prioridade e status reais
- Resposta e histórico no próprio sistema (sem Excel online)
- Parceiros editáveis (não lista hardcoded)
- SLA de 1º atendimento registrado

## Local

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_nio
python manage.py runserver
```

- Portal parceiro: http://127.0.0.1:8000/abrir/
- Área interna: http://127.0.0.1:8000/login/ (`admin` / `admin123`)

## Railway (mesmo Postgres)

Variáveis:

- `DATABASE_URL` = URL do Postgres já existente
- `POSTGRES_SCHEMA=nio_gc_tickets`
- `SECRET_KEY=...`
- `DEBUG=False`
- `ALLOWED_HOSTS=.up.railway.app,seu-dominio`
- `CSRF_TRUSTED_ORIGINS=https://seu-servico.up.railway.app`

### Cloudflare R2 (anexos / imagens)

No Railway o disco do container é **efêmero** — anexos em `/media/` somem no redeploy.
Configure o R2 para persistir uploads:

- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`
- `R2_PUBLIC_BASE_URL` (ex.: `https://pub-xxx.r2.dev`) **ou** `R2_CUSTOM_DOMAIN`

No bucket: ative acesso público (r2.dev ou domínio custom) e CORS permitindo GET do domínio do app.

O `entrypoint.sh` cria o schema e roda migrations automaticamente.
