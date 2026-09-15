"""Campos visíveis/obrigatórios por tipo de demanda (formulário enxuto)."""

from __future__ import annotations

from .models import TipoDemanda

# Contato WhatsApp do solicitante NÃO entra aqui — só o gestor preenche no tratamento,
# exceto quando o tipo pede explicitamente telefone do cliente (ex.: sem_slot, prioridade_elite).

CAMPOS_POR_TIPO: dict[str, dict] = {
    TipoDemanda.AGENDAR_REAGENDAR: {
        "titulo": "Informe pedido, CPF, data e turno",
        "campos": [
            "pedido",
            "documento_cliente",
            "data_desejada",
            "turno",
            "observacoes",
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
        "titulo": "OS, endereço, data agendada no sistema, contato e descrição",
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
            "solicitante_nome",
            "solicitante_contato",
            "descricao",
        ],
        "obrigatorios": [
            "pedido",
            "cep",
            "numero_fachada",
            "data_desejada",
            "turno",
            "solicitante_nome",
            "solicitante_contato",
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
            "solicitante_contato",
            "observacoes",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "tt_vendedor",
            "tt_backoffice",
            "documento_cliente",
            "solicitante_contato",
            "observacoes",
            "descricao",
            "evidencias",
        ],
    },
    TipoDemanda.SEM_SLOT: {
        "titulo": "Diga se o pedido não tem agenda ou se já está agendado sem slot D+1",
        "campos": [
            "variacao_sem_slot",
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
            "data_alternativa",
            "turno",
            "solicitante_contato",
            "evidencias",
        ],
        "obrigatorios": [
            "variacao_sem_slot",
            "pedido",
            "data_desejada",
            "turno",
            "solicitante_contato",
        ],
        "visivel_se": {
            "data_alternativa": {
                "campo": "variacao_sem_slot",
                "valor": "agendado_d1",
            },
        },
        "labels_se": {
            "variacao_sem_slot": {
                "sem_agenda": {
                    "data_desejada": "Data que o cliente deseja agendar",
                },
                "agendado_d1": {
                    "data_desejada": "Data agendada no sistema",
                    "data_alternativa": "Data D+1 sem slot",
                },
            },
        },
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
    TipoDemanda.PENDENCIA_INDEVIDA: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe da pendência",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.AGENDA_NAO_CUMPRIDA: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe da agenda não cumprida",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.SLOT_ALONGADO: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe do slot alongado",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.REAGENDAMENTO_NAO_SOLICITADO: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe do reagendamento não solicitado",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.AGENDAMENTO_CANCELADO: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe do agendamento cancelado",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.CANCELAMENTO_REEMISSAO: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe do cancelamento/reemissão",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.OS_NAO_ATRIBUIDA: {
        "titulo": "OS, SA, cliente, endereço, data e detalhe da OS não atribuída",
        "campos": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "pedido",
            "sa",
            "nome_cliente",
            "solicitante_nome",
            "solicitante_contato",
            "cep",
            "numero_fachada",
            "cidade",
            "data_desejada",
            "tipo_pendencia",
            "recorrencia",
            "descricao",
        ],
    },
    TipoDemanda.VAZAMENTO_DADOS: {
        "titulo": "CPF, data da ocorrência, situação e evidências",
        "campos": [
            "documento_cliente",
            "pedido",
            "data_desejada",
            "descricao",
            "evidencias",
        ],
        "obrigatorios": [
            "documento_cliente",
            "data_desejada",
            "descricao",
            "evidencias",
        ],
    },
    TipoDemanda.GESTAO_ACESSOS: {
        "titulo": "TT, cargo, identidade e detalhe do acesso",
        "campos": [
            "tt",
            "cargo_acesso",
            "solicitante_nome",
            "documento_cliente",
            "rg",
            "email_solicitante",
            "descricao",
        ],
        "obrigatorios": [
            "tt",
            "cargo_acesso",
            "solicitante_nome",
            "documento_cliente",
            "rg",
            "email_solicitante",
            "descricao",
        ],
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
    "sa": "SA",
    "tipo_pendencia": "Tipo da pendência",
    "recorrencia": "Recorrência",
    "variacao_sem_slot": "Situação do pedido",
    "cargo_acesso": "Cargo",
    "rg": "RG",
    "email_solicitante": "E-mail",
}

# Labels específicas por tipo (sobrescreve LABELS_SIMPLES no form)
LABELS_POR_TIPO: dict[str, dict[str, str]] = {
    TipoDemanda.ABRIR_CHAMADO_TI: {
        "tt_vendedor": "TT do vendedor",
        "tt_backoffice": "TT do backoffice de cadastro do pedido com problema",
        "observacoes": "Etapa do erro",
        "solicitante_nome": "Login / nome",
        "solicitante_contato": "Telefone de contato com o cliente",
        "documento_cliente": "CNPJ/CPF do cliente",
        "descricao": "Cenário reportado",
    },
    TipoDemanda.ENDERECO_DOC: {
        "pedido": "Pedido",
        "documento_cliente": "CPF / CNPJ (opcional)",
    },
    TipoDemanda.AGENDAR_REAGENDAR: {
        "documento_cliente": "CPF do cliente",
        "observacoes": "Observações",
    },
    TipoDemanda.ACESSO_APP: {
        "documento_cliente": "CPF",
    },
    TipoDemanda.PRIORIDADE_ELITE: {
        "pedido": "Nº do pedido/OS",
        "data_desejada": "Data agendada no sistema",
        "solicitante_nome": "Nome de contato da instalação",
        "solicitante_contato": "Telefone de contato com o cliente",
        "descricao": "Descrição detalhada da solicitação",
    },
    TipoDemanda.SEM_SLOT: {
        "solicitante_contato": "Telefone do cliente",
        "variacao_sem_slot": "Situação do pedido",
        "data_desejada": "Data que o cliente deseja agendar",
        "data_alternativa": "Data D+1 sem slot",
    },
    TipoDemanda.VAZAMENTO_DADOS: {
        "documento_cliente": "CPF / CNPJ",
        "pedido": "OS (se houver)",
        "data_desejada": "Data da ocorrência",
        "descricao": "Descrever situação",
    },
    TipoDemanda.GESTAO_ACESSOS: {
        "solicitante_nome": "Nome completo",
        "documento_cliente": "CPF / CNPJ",
        "descricao": "Detalhamento da ocorrência",
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

TIPOS_KIT_OPERACAO = (
    TipoDemanda.PENDENCIA_INDEVIDA,
    TipoDemanda.AGENDA_NAO_CUMPRIDA,
    TipoDemanda.SLOT_ALONGADO,
    TipoDemanda.REAGENDAMENTO_NAO_SOLICITADO,
    TipoDemanda.AGENDAMENTO_CANCELADO,
    TipoDemanda.CANCELAMENTO_REEMISSAO,
    TipoDemanda.OS_NAO_ATRIBUIDA,
)
_LABELS_KIT_OPERACAO = {
    "pedido": "OS",
    "data_desejada": "Data de agendamento",
    "descricao": "Detalhamento da ocorrência",
    "solicitante_nome": "Nome de contato",
    "solicitante_contato": "Telefone de contato com o cliente",
}
for _tipo_kit in TIPOS_KIT_OPERACAO:
    LABELS_POR_TIPO[_tipo_kit] = {
        **_LABELS_KIT_OPERACAO,
        **LABELS_POR_TIPO.get(_tipo_kit, {}),
    }


# Campos da demanda mostrados no topo da 1ª aba (o que precisa consultar para responder)
CAMPOS_CONTEXTO_RESPOSTA: dict[str, list[str]] = {
    TipoDemanda.RESET_SENHA: ["tt"],
    TipoDemanda.ENDERECO_DOC: ["pedido", "documento_cliente"],
    TipoDemanda.STATUS_PEDIDO: ["pedido"],
    TipoDemanda.VIABILIDADE: ["cep", "numero_fachada", "endereco_completo"],
    TipoDemanda.AGENDAR_REAGENDAR: [
        "pedido",
        "documento_cliente",
        "data_desejada",
        "turno",
        "observacoes",
    ],
    TipoDemanda.PRIORIDADE_ELITE: [
        "pedido",
        "endereco_completo",
        "data_desejada",
        "turno",
        "solicitante_nome",
        "solicitante_contato",
    ],
    TipoDemanda.ACESSO_APP: ["documento_cliente", "descricao"],
    TipoDemanda.ABRIR_CHAMADO_TI: [
        "tt_vendedor",
        "tt_backoffice",
        "documento_cliente",
        "pedido",
        "solicitante_contato",
        "observacoes",
        "descricao",
    ],
    TipoDemanda.SEM_SLOT: [
        "variacao_sem_slot",
        "pedido",
        "data_desejada",
        "data_alternativa",
        "turno",
        "solicitante_contato",
    ],
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
    TipoDemanda.VAZAMENTO_DADOS: [
        "documento_cliente",
        "pedido",
        "data_desejada",
        "descricao",
    ],
    TipoDemanda.GESTAO_ACESSOS: [
        "tt",
        "solicitante_nome",
        "documento_cliente",
        "descricao",
    ],
}
for _tipo_kit in TIPOS_KIT_OPERACAO:
    CAMPOS_CONTEXTO_RESPOSTA[_tipo_kit] = [
        "pedido",
        "sa",
        "nome_cliente",
        "endereco_completo",
        "data_desejada",
        "tipo_pendencia",
        "recorrencia",
    ]


def schema_tipo(tipo: str) -> dict:
    return CAMPOS_POR_TIPO.get(tipo) or CAMPOS_POR_TIPO[TipoDemanda.OUTROS]


def labels_para_ticket(ticket) -> dict[str, str]:
    tipo = getattr(ticket, "tipo", "") or ""
    labels = {**LABELS_SIMPLES, **LABELS_POR_TIPO.get(tipo, {})}
    cfg = schema_tipo(tipo)
    for trigger, by_val in (cfg.get("labels_se") or {}).items():
        valor = getattr(ticket, trigger, None) or ""
        labels.update((by_val or {}).get(valor) or {})
    return labels


def campos_contexto_resposta(tipo: str) -> list[str]:
    return list(CAMPOS_CONTEXTO_RESPOSTA.get(tipo) or ["pedido"])


def valor_campo_ticket(ticket, name: str) -> str:
    """Valor legível de um campo da demanda para exibir no modal."""
    display = getattr(ticket, f"get_{name}_display", None)
    if callable(display) and name in {
        "turno",
        "turno_alternativo",
        "variacao_sem_slot",
        "recorrencia",
    }:
        return display() or "—"
    if name in {"data_desejada", "data_instalacao", "data_alternativa"}:
        valor = getattr(ticket, name, None)
        return valor.strftime("%d/%m/%Y") if valor else "—"
    valor = getattr(ticket, name, None)
    if valor in (None, ""):
        return "—"
    return str(valor)


def contexto_demanda_para_resposta(ticket) -> list[dict]:
    labels = labels_para_ticket(ticket)
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
            "visivel_se": cfg.get("visivel_se") or {},
            "labels_se": cfg.get("labels_se") or {},
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
    TipoDemanda.VAZAMENTO_DADOS: [
        {
            "name": "retorno_vazamento",
            "label": "Retorno do vazamento",
            "widget": "textarea",
            "required": False,
            "placeholder": "Ex.: incidente registrado / orientação ao PDV",
        },
    ],
    TipoDemanda.GESTAO_ACESSOS: [
        {
            "name": "retorno_acesso",
            "label": "Retorno da gestão de acessos",
            "widget": "textarea",
            "required": False,
            "placeholder": "Ex.: acesso criado / perfil ajustado",
        },
    ],
}
_RETORNO_OPERACAO = [
    {
        "name": "retorno_operacao",
        "label": "Retorno da operação",
        "widget": "textarea",
        "required": False,
        "placeholder": "O que foi feito na esteira / no sistema",
    },
]
for _tipo_kit in TIPOS_KIT_OPERACAO:
    CAMPOS_RESPOSTA_POR_TIPO[_tipo_kit] = list(_RETORNO_OPERACAO)


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
