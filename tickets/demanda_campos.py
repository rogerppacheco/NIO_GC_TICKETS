"""Campos visíveis/obrigatórios por tipo de demanda (formulário enxuto)."""

from __future__ import annotations

from .models import TipoDemanda

# Contato WhatsApp do solicitante NÃO entra aqui — só o gestor preenche no tratamento,
# exceto quando o tipo pede explicitamente telefone do cliente (ex.: sem_slot).

CAMPOS_POR_TIPO: dict[str, dict] = {
    TipoDemanda.AGENDAR_REAGENDAR: {
        "titulo": "Informe pedido, CPF, data e turno",
        "campos": [
            "pedido",
            "documento_cliente",
            "data_desejada",
            "turno",
            "evidencias",
        ],
        "obrigatorios": ["pedido", "documento_cliente", "data_desejada", "turno"],
    },
    TipoDemanda.ENDERECO_DOC: {
        "titulo": "Informe o pedido (CPF opcional)",
        "campos": ["pedido", "documento_cliente"],
        "obrigatorios": ["pedido"],
    },
    TipoDemanda.STATUS_PEDIDO: {
        "titulo": "Informe o pedido",
        "campos": ["pedido"],
        "obrigatorios": ["pedido"],
    },
    TipoDemanda.PRIORIDADE_ELITE: {
        "titulo": "OS, endereço, data e descrição",
        "campos": [
            "pedido",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "turno",
            "descricao",
        ],
        "obrigatorios": [
            "pedido",
            "cep",
            "numero_fachada",
            "data_desejada",
            "turno",
            "descricao",
        ],
    },
    TipoDemanda.RESET_SENHA: {
        "titulo": "Informe a TT",
        "campos": ["tt"],
        "obrigatorios": ["tt"],
    },
    TipoDemanda.VIABILIDADE: {
        "titulo": "CEP e número da fachada",
        "campos": [
            "cep",
            "logradouro",
            "numero_fachada",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
        ],
        "obrigatorios": ["cep", "numero_fachada"],
    },
    TipoDemanda.ACESSO_APP: {
        "titulo": "CPF e evidência do erro",
        "campos": ["documento_cliente", "descricao", "evidencias"],
        "obrigatorios": ["documento_cliente", "evidencias"],
    },
    TipoDemanda.ABRIR_CHAMADO_TI: {
        "titulo": "Informe as TTs, o erro e as evidências",
        "campos": [
            "pedido",
            "documento_cliente",
            "tt_vendedor",
            "tt_backoffice",
            "solicitante_nome",
            "observacoes",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "tt_vendedor",
            "tt_backoffice",
            "observacoes",
            "descricao",
            "evidencias",
        ],
    },
    TipoDemanda.SEM_SLOT: {
        "titulo": "Pedido, endereço, data e telefone do cliente",
        "campos": [
            "pedido",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "turno",
            "solicitante_contato",
            "evidencias",
        ],
        "obrigatorios": ["pedido", "data_desejada", "turno", "solicitante_contato"],
    },
    TipoDemanda.INSTALACAO_FISICA: {
        "titulo": "OS, endereço e descrição",
        "campos": [
            "pedido",
            "cep",
            "logradouro",
            "numero_fachada",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "descricao",
        ],
        "obrigatorios": ["pedido", "descricao"],
    },
    TipoDemanda.REPARO: {
        "titulo": "OS recém instalada (até 14 dias): duas opções de retorno e a solicitação",
        "campos": [
            "pedido",
            "nome_cliente",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "solicitante_contato",
            "data_instalacao",
            "data_desejada",
            "turno",
            "data_alternativa",
            "turno_alternativo",
            "motivo_reparo",
            "descricao",
        ],
        "obrigatorios": [
            "pedido",
            "nome_cliente",
            "cep",
            "numero_fachada",
            "solicitante_contato",
            "data_instalacao",
            "data_desejada",
            "turno",
            "data_alternativa",
            "turno_alternativo",
            "motivo_reparo",
        ],
        "descricao_se": {"campo": "motivo_reparo", "valor": "outro"},
    },
    TipoDemanda.OUTROS: {
        "titulo": "Descreva a demanda",
        "campos": ["pedido", "descricao", "evidencias"],
        "obrigatorios": ["descricao"],
    },
}

LABELS_SIMPLES = {
    "tipo": "Tipo da demanda",
    "parceiro": "Parceiro / PDV",
    "pedido": "Pedido / OS",
    "documento_cliente": "CPF / CNPJ",
    "tt": "TT",
    "tt_vendedor": "TT do vendedor",
    "tt_backoffice": "TT do backoffice de cadastro do pedido com problema",
    "data_desejada": "Data desejada",
    "turno": "Turno",
    "cep": "CEP",
    "logradouro": "Logradouro",
    "numero_fachada": "Nº",
    "complemento": "Complemento",
    "bairro": "Bairro",
    "cidade": "Cidade",
    "uf": "UF",
    "endereco_completo": "Endereço completo",
    "descricao": "Descrição",
    "observacoes": "Etapa do erro",
    "solicitante_nome": "Login / nome",
    "solicitante_contato": "Telefone do cliente",
    "nome_cliente": "Nome do cliente",
    "data_instalacao": "Data da instalação",
    "data_alternativa": "Opção 2 — Data",
    "turno_alternativo": "Opção 2 — Turno",
    "motivo_reparo": "Solicitação",
    "evidencias": "Evidências (anexo)",
}

# Labels específicas por tipo (sobrescreve LABELS_SIMPLES no form)
LABELS_POR_TIPO: dict[str, dict[str, str]] = {
    TipoDemanda.ABRIR_CHAMADO_TI: {
        "tt_vendedor": "TT do vendedor",
        "tt_backoffice": "TT do backoffice de cadastro do pedido com problema",
        "observacoes": "Etapa do erro",
        "solicitante_nome": "Login / nome",
    },
    TipoDemanda.ENDERECO_DOC: {
        "pedido": "Pedido",
        "documento_cliente": "CPF / CNPJ (opcional)",
    },
    TipoDemanda.AGENDAR_REAGENDAR: {
        "documento_cliente": "CPF do cliente",
    },
    TipoDemanda.ACESSO_APP: {
        "documento_cliente": "CPF",
    },
    TipoDemanda.SEM_SLOT: {
        "solicitante_contato": "Telefone do cliente",
    },
    TipoDemanda.REPARO: {
        "solicitante_contato": "Contato do cliente",
        "data_desejada": "Opção 1 — Data",
        "turno": "Opção 1 — Turno",
        "data_alternativa": "Opção 2 — Data",
        "turno_alternativo": "Opção 2 — Turno",
        "data_instalacao": "Data da instalação",
        "nome_cliente": "Nome do cliente",
        "motivo_reparo": "Solicitação",
        "descricao": "Descreva a solicitação",
    },
}


# Campos da demanda mostrados no topo da 1ª aba (o que precisa consultar para responder)
CAMPOS_CONTEXTO_RESPOSTA: dict[str, list[str]] = {
    TipoDemanda.RESET_SENHA: ["tt"],
    TipoDemanda.ENDERECO_DOC: ["pedido", "documento_cliente"],
    TipoDemanda.STATUS_PEDIDO: ["pedido"],
    TipoDemanda.VIABILIDADE: ["cep", "numero_fachada", "endereco_completo"],
    TipoDemanda.AGENDAR_REAGENDAR: ["pedido", "documento_cliente", "data_desejada", "turno"],
    TipoDemanda.PRIORIDADE_ELITE: ["pedido", "endereco_completo", "data_desejada", "turno"],
    TipoDemanda.ACESSO_APP: ["documento_cliente", "descricao"],
    TipoDemanda.ABRIR_CHAMADO_TI: ["tt_vendedor", "tt_backoffice", "pedido", "observacoes"],
    TipoDemanda.SEM_SLOT: ["pedido", "data_desejada", "turno", "solicitante_contato"],
    TipoDemanda.INSTALACAO_FISICA: ["pedido", "endereco_completo", "descricao"],
    TipoDemanda.REPARO: [
        "pedido",
        "nome_cliente",
        "data_instalacao",
        "data_desejada",
        "turno",
        "data_alternativa",
        "turno_alternativo",
    ],
    TipoDemanda.OUTROS: ["pedido", "descricao"],
}


def schema_tipo(tipo: str) -> dict:
    return CAMPOS_POR_TIPO.get(tipo) or CAMPOS_POR_TIPO[TipoDemanda.OUTROS]


def campos_contexto_resposta(tipo: str) -> list[str]:
    return list(CAMPOS_CONTEXTO_RESPOSTA.get(tipo) or ["pedido"])


def valor_campo_ticket(ticket, name: str) -> str:
    """Valor legível de um campo da demanda para exibir no modal."""
    if name == "turno":
        return ticket.get_turno_display() or "—"
    if name == "turno_alternativo":
        return ticket.get_turno_alternativo_display() or "—"
    if name in {"data_desejada", "data_instalacao", "data_alternativa"}:
        valor = getattr(ticket, name, None)
        return valor.strftime("%d/%m/%Y") if valor else "—"
    valor = getattr(ticket, name, None)
    if valor in (None, ""):
        return "—"
    return str(valor)


def contexto_demanda_para_resposta(ticket) -> list[dict]:
    labels = {**LABELS_SIMPLES, **LABELS_POR_TIPO.get(ticket.tipo, {})}
    itens = []
    for name in campos_contexto_resposta(ticket.tipo):
        itens.append(
            {
                "name": name,
                "label": labels.get(name, name),
                "valor": valor_campo_ticket(ticket, name),
            }
        )
    return itens


ABAS_TRATAMENTO_EXTRAS = [
    ("complemento_retorno", "Complemento"),
    ("resultado_status", "STATUS"),
    ("status", "Fila"),
    ("nota_interna", "DETALHES"),
    ("solicitante_contato", "WhatsApp"),
]


def montar_abas_tratamento(treat_form) -> list[dict]:
    """Abas do modal: a 1ª é sempre o campo de resposta da demanda."""
    tabs: list[dict] = []
    for campo in treat_form.campos_resposta_defs:
        tabs.append(
            {
                "id": campo["name"],
                "label": campo["label"],
                "field_names": [campo["name"]],
                "principal": not tabs,
            }
        )
    if not tabs:
        tabs.append(
            {
                "id": "resposta",
                "label": "Resposta",
                "field_names": ["complemento_retorno"],
                "principal": True,
            }
        )
    usados = {n for t in tabs for n in t["field_names"]}
    for name, label in ABAS_TRATAMENTO_EXTRAS:
        if name in usados:
            continue
        field_names = ["status", "prioridade"] if name == "status" else [name]
        tabs.append(
            {
                "id": name,
                "label": label,
                "field_names": field_names,
                "principal": False,
            }
        )
    return tabs


def schema_para_js() -> dict:
    return {
        tipo: {
            "titulo": cfg["titulo"],
            "campos": cfg["campos"],
            "obrigatorios": cfg["obrigatorios"],
            "labels": LABELS_POR_TIPO.get(tipo, {}),
            "descricao_se": cfg.get("descricao_se"),
        }
        for tipo, cfg in CAMPOS_POR_TIPO.items()
    }


# Campos que o gestor preenche ao responder (por tipo)
CAMPOS_RESPOSTA_POR_TIPO: dict[str, list[dict]] = {
    TipoDemanda.RESET_SENHA: [
        {
            "name": "senha_resetada",
            "label": "Senha resetada",
            "help": "Senha gerada/informada ao parceiro",
            "widget": "text",
            "required": True,
            "placeholder": "Ex.: Nio@1234",
        },
    ],
    TipoDemanda.ENDERECO_DOC: [
        {
            "name": "endereco_consultado",
            "label": "Endereço consultado",
            "help": "Endereço encontrado no sistema para este pedido",
            "widget": "textarea",
            "required": True,
            "placeholder": "Rua..., nº..., bairro..., cidade/UF, CEP...",
        },
    ],
    TipoDemanda.STATUS_PEDIDO: [
        {
            "name": "status_agendamento",
            "label": "Status / agendamento atual",
            "help": "Situação encontrada no sistema",
            "widget": "textarea",
            "required": True,
            "placeholder": "Ex.: Agendado 12/08 manhã · técnico João",
        },
    ],
    TipoDemanda.VIABILIDADE: [
        {
            "name": "resultado_viabilidade",
            "label": "Resultado da viabilidade",
            "widget": "textarea",
            "required": True,
            "placeholder": "Ex.: Viável / Inviável — observações",
        },
    ],
    TipoDemanda.AGENDAR_REAGENDAR: [
        {
            "name": "agendamento_confirmado",
            "label": "Agendamento confirmado",
            "widget": "text",
            "required": False,
            "placeholder": "Ex.: 15/08 — manhã",
        },
    ],
    TipoDemanda.ACESSO_APP: [
        {
            "name": "numero_chamado",
            "label": "Nº do chamado",
            "widget": "text",
            "required": False,
            "placeholder": "Número do chamado aberto",
        },
    ],
    TipoDemanda.ABRIR_CHAMADO_TI: [
        {
            "name": "numero_chamado",
            "label": "Nº do chamado TI",
            "widget": "text",
            "required": False,
            "placeholder": "Número do chamado",
        },
    ],
    TipoDemanda.PRIORIDADE_ELITE: [
        {
            "name": "retorno_elite",
            "label": "Retorno / protocolo Elite",
            "widget": "text",
            "required": False,
            "placeholder": "Ex.: encaminhado ao grupo / protocolo",
        },
    ],
    TipoDemanda.SEM_SLOT: [
        {
            "name": "retorno_liberacao",
            "label": "Retorno da liberação",
            "widget": "textarea",
            "required": False,
            "placeholder": "Ex.: slot liberado para 20/08 tarde",
        },
    ],
    TipoDemanda.INSTALACAO_FISICA: [
        {
            "name": "retorno_sinalizacao",
            "label": "Retorno da sinalização",
            "widget": "textarea",
            "required": False,
        },
    ],
    TipoDemanda.REPARO: [
        {
            "name": "retorno_reparo",
            "label": "Retorno do reparo",
            "widget": "textarea",
            "required": False,
            "placeholder": "Ex.: técnico agendado / protocolo de reparo",
        },
    ],
    TipoDemanda.OUTROS: [
        {
            "name": "retorno_livre",
            "label": "Resposta ao parceiro",
            "widget": "textarea",
            "required": False,
        },
    ],
}


def campos_resposta(tipo: str) -> list[dict]:
    """Campos ativos para resposta: prioriza config no banco; senão usa padrão."""
    try:
        from .models import ConfigRespostaTipo

        cfg = ConfigRespostaTipo.objects.filter(tipo=tipo).first()
        if cfg and cfg.campos is not None:
            return cfg.campos_ativos()
    except Exception:
        pass
    return list(
        CAMPOS_RESPOSTA_POR_TIPO.get(tipo) or CAMPOS_RESPOSTA_POR_TIPO[TipoDemanda.OUTROS]
    )


def catalogo_campos_resposta() -> list[dict]:
    """Catálogo único de campos disponíveis para montar por tipo."""
    vistos: dict[str, dict] = {}
    for lista in CAMPOS_RESPOSTA_POR_TIPO.values():
        for campo in lista:
            vistos.setdefault(campo["name"], dict(campo))
    # campos extras úteis
    for extra in (
        {
            "name": "observacao_parceiro",
            "label": "Observação ao parceiro",
            "widget": "textarea",
            "required": False,
        },
        {
            "name": "protocolo_externo",
            "label": "Protocolo externo",
            "widget": "text",
            "required": False,
        },
    ):
        vistos.setdefault(extra["name"], extra)
    return sorted(vistos.values(), key=lambda c: c["label"].lower())


def garantir_config_resposta_padrao() -> int:
    """Cria configs default para tipos que ainda não existem. Retorna qtd criada."""
    from .models import ConfigRespostaTipo

    criados = 0
    for tipo, campos in CAMPOS_RESPOSTA_POR_TIPO.items():
        _, created = ConfigRespostaTipo.objects.get_or_create(
            tipo=tipo,
            defaults={
                "campos": [
                    {**c, "ativo": True} for c in campos
                ]
            },
        )
        if created:
            criados += 1
    return criados


def montar_texto_retorno(tipo: str, dados: dict, complemento: str = "") -> str:
    """Monta o texto RETORNO a partir dos campos estruturados."""
    partes: list[str] = []
    for campo in campos_resposta(tipo):
        valor = (dados or {}).get(campo["name"])
        if valor and str(valor).strip():
            partes.append(f"{campo['label']}: {str(valor).strip()}")
    if complemento and complemento.strip():
        # evita duplicar se o complemento já for o texto montado
        comp = complemento.strip()
        if comp not in partes and not any(comp == p.split(": ", 1)[-1] for p in partes):
            partes.append(comp)
    return "\n".join(partes)
