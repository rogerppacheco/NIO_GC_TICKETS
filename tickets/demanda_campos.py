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
}


def schema_tipo(tipo: str) -> dict:
    return CAMPOS_POR_TIPO.get(tipo) or CAMPOS_POR_TIPO[TipoDemanda.OUTROS]


def schema_para_js() -> dict:
    return {
        tipo: {
            "titulo": cfg["titulo"],
            "campos": cfg["campos"],
            "obrigatorios": cfg["obrigatorios"],
            "labels": LABELS_POR_TIPO.get(tipo, {}),
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
    return CAMPOS_RESPOSTA_POR_TIPO.get(tipo) or CAMPOS_RESPOSTA_POR_TIPO[TipoDemanda.OUTROS]


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
