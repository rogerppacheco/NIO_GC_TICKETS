"""Isola auth/sessão deste app no schema próprio.

O Postgres é compartilhado com a viabilidade. As tabelas Django
(auth_user, django_session, …) ficaram em public na primeira migração.
Com search_path=nio_gc_tickets,public o app passa a usar as cópias locais.
Não apaga nem altera public.auth_user (outros sistemas continuam iguais).
"""

from __future__ import annotations

import re

from django.conf import settings

SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TABELAS_AUTH = (
    "auth_user",
    "auth_group",
    "auth_user_groups",
    "auth_user_user_permissions",
    "auth_group_permissions",
    "django_session",
    "django_admin_log",
)


def nome_schema() -> str:
    schema = (getattr(settings, "POSTGRES_SCHEMA", None) or "nio_gc_tickets").strip()
    if not SCHEMA_RE.fullmatch(schema):
        raise ValueError(f"POSTGRES_SCHEMA inválido: {schema!r}")
    return schema


def _try_sql(cursor, sql: str) -> bool:
    cursor.execute("SAVEPOINT isol_opcional")
    try:
        cursor.execute(sql)
    except Exception:
        cursor.execute("ROLLBACK TO SAVEPOINT isol_opcional")
        cursor.execute("RELEASE SAVEPOINT isol_opcional")
        return False
    cursor.execute("RELEASE SAVEPOINT isol_opcional")
    return True


def _existe_tabela(cursor, schema: str, tabela: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        )
        """,
        [schema, tabela],
    )
    return bool(cursor.fetchone()[0])


def _clonar_estrutura(cursor, origem: str, destino: str, tabela: str) -> None:
    if _existe_tabela(cursor, destino, tabela):
        return
    if not _existe_tabela(cursor, origem, tabela):
        return
    cursor.execute(
        f'CREATE TABLE "{destino}"."{tabela}" '
        f'(LIKE "{origem}"."{tabela}" INCLUDING CONSTRAINTS INCLUDING INDEXES INCLUDING COMMENTS)'
    )


def _ajustar_sequence_id(cursor, schema: str, tabela: str) -> None:
    if not _existe_tabela(cursor, schema, tabela):
        return
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = 'id'
        """,
        [schema, tabela],
    )
    if not cursor.fetchone():
        return
    seq = f"{schema}.{tabela}_id_seq"
    cursor.execute(f'CREATE SEQUENCE IF NOT EXISTS "{schema}"."{tabela}_id_seq"')
    _try_sql(
        cursor,
        f'ALTER TABLE "{schema}"."{tabela}" '
        f"ALTER COLUMN id SET DEFAULT nextval('{seq}')",
    )
    _try_sql(
        cursor,
        f"""
        SELECT setval(
            '{seq}',
            GREATEST(COALESCE((SELECT MAX(id) FROM "{schema}"."{tabela}"), 1), 1),
            true
        )
        """,
    )


def _copiar_usuarios_deste_app(cursor, schema: str) -> int:
    if not _existe_tabela(cursor, "public", "auth_user"):
        return 0
    if not _existe_tabela(cursor, schema, "auth_user"):
        return 0
    if not _existe_tabela(cursor, schema, "tickets_perfilstaff"):
        return 0

    partes = [f'SELECT user_id FROM "{schema}".tickets_perfilstaff']
    refs = (
        ("tickets_parceiro", "especialista_id"),
        ("tickets_ticket", "atendente_id"),
        ("tickets_mensagem", "autor_id"),
        ("tickets_anexo", "enviado_por_id"),
        ("tickets_encaminhamento", "criado_por_id"),
    )
    for tabela, coluna in refs:
        if _existe_tabela(cursor, schema, tabela):
            partes.append(
                f'SELECT {coluna} FROM "{schema}"."{tabela}" WHERE {coluna} IS NOT NULL'
            )

    union_sql = " UNION ".join(partes)
    sql = f"""
        INSERT INTO "{schema}".auth_user
        SELECT u.*
        FROM public.auth_user u
        WHERE (
            u.id IN ({union_sql})
            OR lower(u.username) IN ('admin', 'roger')
        )
        AND NOT EXISTS (
            SELECT 1 FROM "{schema}".auth_user d WHERE d.id = u.id
        )
        """
    sql_id = sql.replace(
        f'INSERT INTO "{schema}".auth_user',
        f'INSERT INTO "{schema}".auth_user OVERRIDING SYSTEM VALUE',
        1,
    )
    if not _try_sql(cursor, sql_id):
        cursor.execute(sql)
    return cursor.rowcount or 0


def _on_delete_sql(confdeltype: str) -> str:
    return {
        "c": "ON DELETE CASCADE",
        "n": "ON DELETE SET NULL",
        "r": "ON DELETE RESTRICT",
        "d": "ON DELETE SET DEFAULT",
        "a": "",
    }.get(confdeltype, "")


def _retarget_fks_auth_user(cursor, schema: str) -> None:
    if not _existe_tabela(cursor, schema, "auth_user"):
        return
    cursor.execute(
        """
        SELECT
            nsp.nspname AS schema_nome,
            rel.relname AS tabela,
            con.conname AS constraint_nome,
            att.attname AS coluna,
            con.confdeltype
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        JOIN pg_class frel ON frel.oid = con.confrelid
        JOIN pg_namespace fnsp ON fnsp.oid = frel.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ord) ON TRUE
        JOIN pg_attribute att
            ON att.attrelid = rel.oid AND att.attnum = ck.attnum
        WHERE con.contype = 'f'
          AND fnsp.nspname = 'public'
          AND frel.relname = 'auth_user'
          AND nsp.nspname = %s
          AND ck.ord = 1
        """,
        [schema],
    )
    fks = cursor.fetchall()
    for schema_nome, tabela, constraint_nome, coluna, confdeltype in fks:
        cursor.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            [schema_nome, tabela, coluna],
        )
        nullable = (cursor.fetchone() or ["YES"])[0] == "YES"
        if nullable:
            cursor.execute(
                f"""
                UPDATE "{schema_nome}"."{tabela}"
                SET "{coluna}" = NULL
                WHERE "{coluna}" IS NOT NULL
                  AND "{coluna}" NOT IN (SELECT id FROM "{schema}".auth_user)
                """
            )
        cursor.execute(
            f'ALTER TABLE "{schema_nome}"."{tabela}" DROP CONSTRAINT "{constraint_nome}"'
        )
        on_delete = _on_delete_sql(confdeltype)
        cursor.execute(
            f'ALTER TABLE "{schema_nome}"."{tabela}" '
            f'ADD CONSTRAINT "{constraint_nome}" '
            f'FOREIGN KEY ("{coluna}") REFERENCES "{schema}".auth_user (id) {on_delete}'
        )


def _fk_admin_log(cursor, schema: str) -> None:
    if not _existe_tabela(cursor, schema, "django_admin_log"):
        return
    cursor.execute(
        """
        SELECT 1 FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = %s AND rel.relname = 'django_admin_log'
          AND con.contype = 'f' AND con.conname = 'django_admin_log_user_id_fkey'
        """,
        [schema],
    )
    if cursor.fetchone():
        return
    _try_sql(
        cursor,
        f"""
        ALTER TABLE "{schema}".django_admin_log
        ADD CONSTRAINT django_admin_log_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES "{schema}".auth_user (id)
        ON DELETE CASCADE
        """,
    )


def isolar_auth_schema(connection) -> dict:
    """Cria auth local no schema do app e copia só usuários usados aqui."""
    if connection.vendor != "postgresql":
        return {"ok": True, "motivo": "nao_postgres"}

    schema = nome_schema()
    with connection.cursor() as cursor:
        if not _existe_tabela(cursor, "public", "auth_user"):
            return {"ok": True, "motivo": "sem_auth_publico"}

        for tabela in TABELAS_AUTH:
            _clonar_estrutura(cursor, "public", schema, tabela)

        copiados = _copiar_usuarios_deste_app(cursor, schema)
        _ajustar_sequence_id(cursor, schema, "auth_user")
        _retarget_fks_auth_user(cursor, schema)
        _fk_admin_log(cursor, schema)

        cursor.execute(f'SELECT COUNT(*) FROM "{schema}".auth_user')
        total = cursor.fetchone()[0]

    return {"ok": True, "copiados": copiados, "total_local": total, "schema": schema}
