"""
Automação SmartRiser (V.top / V.tal) a partir do Projeto Vertical.

Port do site-record (crm_app/services_vtop_smartriser.py). A chave interna
"cdoi_id" do payload é o id da SolicitacaoVertical.

Princípios de sessão:
- NÃO faz logout em nenhum momento.
- Persiste cookies em storage_state (arquivo) após o login manual.
- Reusa a sessão nos próximos acionamentos — evita relogar o IdP corporativo.
- Login manual: abre o browser, aguarda o usuário digitar credenciais e
  o botão "Já coloquei a senha" no CDOI; só então clica em EFETUAR LOGIN.

Fluxo (passos):
  1. Login IdP (manual + clique automatizado)
  2. Portal V.top → card SmartRiser
  3. Brownfield (risers em HPs até 2024)
  4. FAB "+" → modal Cadastro de nova obra
  5. Preencher + Salvar obra
  6. Modal coordenadas (lat/long) + Salvar
  7. obra.jsp Cadastro → dados + anexos → disquete → validar
"""

from __future__ import annotations

import logging
import difflib
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import caches
from django.db import close_old_connections

logger = logging.getLogger(__name__)


class _VtopCache:
    """Cache compartilhado entre workers do gunicorn (alias "vtop" em settings.CACHES)."""

    @staticmethod
    def _backend():
        try:
            return caches["vtop"]
        except Exception:
            return caches["default"]

    def get(self, *args: Any, **kwargs: Any) -> Any:
        return self._backend().get(*args, **kwargs)

    def set(self, *args: Any, **kwargs: Any) -> Any:
        return self._backend().set(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        return self._backend().delete(*args, **kwargs)


cache = _VtopCache()

try:
    from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Browser = BrowserContext = Page = None  # type: ignore
    sync_playwright = None  # type: ignore
    logger.warning("[VTOP] Playwright não instalado. Automação SmartRiser desabilitada.")

# =============================================================================
# URLs e configuração
# =============================================================================

VTOP_HOME_URL = "https://vtop.vtal.com/appvtop/"
VTOP_SMARTRISER_URL = "https://vtop.vtal.com/appvtop/smartriser/"
VTOP_LOGIN_URL = (
    "https://login.vtal.com/nidp/app/login"
    "?id=VtalCorpPwdLessId&sid=2&option=credential&sid=2"
    "&target=https%3A%2F%2Flogin.vtal.com%2Fnidp%2Foauth%2Fnam%2Fauthz"
    "%3Fclient_id%3D34132d5e-35ac-40c5-a2b3-2123a343ef13"
    "%26redirect_uri%3Dhttps%3A%2F%2Fvtop.vtal.com%2Fcallback%3Fw%3D1"
    "%26response_type%3Dcode%26scope%3Dvtal_operacao%26grant_type%3Dclient_credentials"
)

# Pré-venda por obra = teto de 18% dos HPs do bloco (regra BN / SmartRiser)
PRE_VENDA_PCT_BLOCO = 0.18


def calcular_pre_venda_bloco(hps: int) -> int:
    """Retorna ceil(18% × HPs do bloco). Ex.: 16→3, 18→4."""
    hps_i = int(hps or 0)
    if hps_i <= 0:
        return 0
    return max(1, int(math.ceil(hps_i * PRE_VENDA_PCT_BLOCO)))

DEFAULT_TIMEOUT_MS = 30_000
LOGIN_WAIT_SECONDS = 15 * 60  # tempo máximo aguardando o usuário digitar a senha / ler o QR
QR_POLL_MS = 1500
# Sem QR visível (WebSocket V.tal caiu / QR expirou) por este tempo → recarrega a tela de login
QR_RECARREGAR_APOS_S = 45
# Após sair da tela de login, espera o portal V.top renderizar antes de dar login como falho
LOGIN_CONFIRMAR_S = 30
# Tela Brownfield: espera ficar pronta / tabela surgir, e quantas vezes relança a pesquisa
BROWNFIELD_PRONTA_S = 30
BROWNFIELD_TABELA_S = 30
BROWNFIELD_TENTATIVAS = 3
# Após clicar Salvar na obra: espera obra.jsp / modal fechar / mensagem (e um respiro após o sinal)
SALVAR_OBRA_TIMEOUT_S = 45
SALVAR_OBRA_APOS_SINAL_S = 5
# Nome de logradouro parecido (grafia diferente) na grade → trava a criação
LOGRADOURO_SIMILARIDADE_MIN = 0.85
# Teto de páginas no inventário Brownfield (grade da V.tal lista 15 obras por página)
INVENTARIO_MAX_PAGINAS = 30

# Gunicorn roda N workers: estado e comandos passam pelo cache (DB) para qualquer worker responder
CACHE_KEY_ESTADO = "vtop:estado"
CACHE_KEY_COMANDO = "vtop:comando"
CACHE_TTL_S = 6 * 60 * 60
# Estado ativo sem atualização há mais que isso é considerado órfão (worker reiniciado)
ESTADO_ORFAO_APOS_S = 5 * 60
_db_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vtop-db")


def _db_op(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """
    Executa acesso ao banco (ORM/cache) numa thread própria: a thread da automação roda o
    event loop do Playwright sync e o Django bloqueia ORM ali (SynchronousOnlyOperation).
    """
    def _executar() -> Any:
        close_old_connections()
        return fn(*args, **kwargs)

    return _db_executor.submit(_executar).result(timeout=30)


STATUS_ATIVOS = {
    "starting", "awaiting_credentials", "awaiting_qr", "clicking_login", "logged_in",
    "navigating", "filling_obra", "filling_coords", "filling_cadastro", "uploading",
    "saving", "validating",
}


def _storage_state_path() -> str:
    path = getattr(
        settings,
        "VTOP_STORAGE_STATE",
        os.path.join(settings.BASE_DIR, ".playwright_vtop_state.json"),
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _garantir_storage_state_arquivo() -> bool:
    """
    Garante arquivo de sessão Playwright.
    Em Railway o disco é efêmero — use VTOP_STORAGE_STATE_B64 (JSON em base64
    gerado localmente com scripts/teste_login_vtop.py + publicar_sessao_vtop_railway.py).
    """
    path = _storage_state_path()
    if os.path.isfile(path) and os.path.getsize(path) > 50:
        return True

    b64 = (getattr(settings, "VTOP_STORAGE_STATE_B64", None) or os.environ.get("VTOP_STORAGE_STATE_B64") or "").strip()
    if not b64:
        return False
    try:
        import base64

        raw = base64.b64decode(b64, validate=False)
        if raw[:1] != b"{":
            raw = b64.encode("utf-8")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(raw)
        logger.info(
            "[VTOP] Storage state materializado de VTOP_STORAGE_STATE_B64 (%s bytes) -> %s",
            len(raw),
            path,
        )
        return True
    except Exception:
        logger.exception("[VTOP] Falha ao materializar VTOP_STORAGE_STATE_B64")
        return False


def _headless() -> bool:
    return bool(getattr(settings, "VTOP_HEADLESS", False))


# =============================================================================
# Mapa de campos CDOI → V.top
# =============================================================================
#
# Gestão CDOI (CdoiSolicitacao)          →  SmartRiser
# --------------------------------------    ---------------------------------
# nome_condominio                        →  Cadastro: NOME DO CONDOMINIO
#                                           Obra: FACHADA (opcional / espelho do nome curto)
# nome_sindico                           →  Cadastro: NOME DO SÍNDICO
# contato_sindico                        →  Cadastro: NÚMERO DE CONTATO SÍNDICO/CONDOMÍNIO
# cep                                    →  (só no CDOI; V.top usa endereço estruturado)
# logradouro                             →  Obra: LOGRADOURO
# numero                                 →  Obra: NUM + Cadastro NUM FACHADA
# bairro                                 →  Obra: BAIRRO
# cidade                                 →  Obra: LOCALIDADE
# uf                                     →  Obra: UF
# latitude / longitude                   →  Modal mapa + LOCALIZAÇÃO
# total_hps                              →  Obra: QUANTIDADE UMS + Cadastro TOTAL DE HPs
# pre_venda                               →  Cadastro: PRÉ-VENDA = ceil(18% × HPs do bloco)
# infraestrutura_tipo + shaft + blocos   →  Cadastro: CARACTERÍSTICAS DO PRÉDIO
# blocos[].nome / andares / aptos        →  Cadastro: BLOCOS / ANDARES / texto características
# link_carta_sindico (R2)                →  Cadastro: CARTA DE AUTORIZAÇÃO (upload)
# link_fotos_fachada (R2)                →  Cadastro: FOTOS DA FACHADA (upload)
# id (CDOI)                              →  Obra: CDOI (código interno Record — conferir regra)
# —                                      →  Obra: COD SURVEY (vazio / manual se necessário)
# —                                      →  Obra: ESTAÇÃO / CÉLULA (vazio até termos regra)
# —                                      →  Obra: MÊS (default: mês atual no portal)
# parceiro.codigo_pdv (PDV do acionamento) →  Cadastro: CÓDIGO DO PARCEIRO (SAP)
# complemento (montado dos blocos)       →  Obra: COMPLEMENTO


SELETORES: Dict[str, Dict[str, str]] = {
    "login": {
        "btn_efetuar": 'button:has-text("EFETUAR LOGIN"), button:has-text("EFETUAR"), button[type="submit"]',
    },
    "portal": {
        "card_smartriser": (
            'div:has-text("SmartRiser - Rede Inteligente Vertical"), '
            'a:has-text("SmartRiser"), '
            'text=SmartRiser - Rede Inteligente Vertical'
        ),
    },
    "smartriser": {
        "brownfield": (
            'text=/Brownfield.*risers.*2024/i, '
            'a:has-text("Brownfield"), '
            'div:has-text("Brownfield"):has-text("2024")'
        ),
        "fab_mais": (
            'button:has-text("+"), '
            '[aria-label="+"], '
            'button.btn-floating:has-text("+"), '
            '.fixed-action-btn a'
        ),
    },
    "obra_modal": {
        "titulo": 'text=Cadastro de nova obra',
        "cod_survey": 'input[name*="survey" i], label:has-text("COD SURVEY") ~ input, label:has-text("COD SURVEY") + input',
        "uf": 'select:near(:text("UF")), label:has-text("UF") ~ select, label:has-text("UF") + select',
        "localidade": 'input:near(:text("LOCALIDADE")), label:has-text("LOCALIDADE") ~ input',
        "estacao": 'input:near(:text("ESTAÇÃO")), label:has-text("ESTAÇÃO") ~ input, label:has-text("ESTACAO") ~ input',
        "mes": 'select:near(:text("MÊS")), label:has-text("MÊS") ~ select',
        "logradouro": 'input:near(:text("LOGRADOURO")), label:has-text("LOGRADOURO") ~ input',
        "num": 'input:near(:text("NUM")), label:has-text("NUM") ~ input',
        "fachada": 'input:near(:text("FACHADA")), label:has-text("FACHADA") ~ input',
        "bairro": 'input:near(:text("BAIRRO")), label:has-text("BAIRRO") ~ input',
        "complemento": 'input:near(:text("COMPLEMENTO")), label:has-text("COMPLEMENTO") ~ input',
        "celula": 'input:near(:text("CÉLULA")), label:has-text("CÉLULA") ~ input, label:has-text("CELULA") ~ input',
        "cdoi": 'input:near(:text("CDOI")), label:has-text("CDOI") ~ input',
        "qtd_ums": 'input:near(:text("QUANTIDADE UMS")), label:has-text("QUANTIDADE UMS") ~ input',
        "btn_salvar": 'button:has-text("Salvar")',
        "btn_cancelar": 'button:has-text("Cancelar")',
    },
    "coords_modal": {
        "titulo": 'text=/Selecione no mapa|Latitude/i',
        "latitude": 'input:near(:text("Latitude")), label:has-text("Latitude") ~ input, input[name*="lat" i]',
        "longitude": 'input:near(:text("Longitude")), label:has-text("Longitude") ~ input, input[name*="lng" i], input[name*="long" i]',
        "btn_procurar": 'button:has-text("Procurar")',
        "btn_salvar": 'button:has-text("Salvar")',
    },
    # Etapa 1 (Cadastro) em obra.jsp — IDs dinâmicos: edit_{obra_id}_1_{n}
    # Mapeado em 2026-08 (obra 9416 / BLOCO 05):
    #   _2 NOME DO CONDOMINIO
    #   _3 NOME DO SINDICO
    #   _4 NÚMERO DE CONTATO SÍNDICO/CONDOMINIO
    #   _5 CARTA DE AUTORIZAÇÃO (texto; anexo via fa-square-plus → addDocFoto)
    #   _6 CÓDIGO DO PARCEIRO (SAP)
    #   _7 QUANTIDADE DE BLOCOS… → #input_blocos #input_andares #input_total_hps #input_prevenda + edit_*_1_8
    #   _9 FOTOS DA FAIXADA DO CONDOMINIO (texto; anexo via +)
    # Botões: #btn_salvarEtapa | #btn_validarEtapa | #btn_reprovarEtapa
    "cadastro_obra": {
        "nome_condominio": "#edit_{obra_id}_1_2",
        "nome_sindico": "#edit_{obra_id}_1_3",
        "contato": "#edit_{obra_id}_1_4",
        "carta_texto": "#edit_{obra_id}_1_5",
        "codigo_sap": "#edit_{obra_id}_1_6",
        "caracteristicas": "#edit_{obra_id}_1_8",
        "fotos_texto": "#edit_{obra_id}_1_9",
        "input_blocos": "#input_blocos",
        "input_andares": "#input_andares",
        "input_total_hps": "#input_total_hps",
        "input_prevenda": "#input_prevenda",
        "btn_salvar_etapa": "#btn_salvarEtapa",
        "btn_validar_etapa": "#btn_validarEtapa",
        "btn_reprovar_etapa": "#btn_reprovarEtapa",
        "btn_salvar_disquete": "#btn_salvarEtapa, button[title*='Salvar' i]",
        "btn_validar": 'button:has(.fa-check), button[title*="validar" i], a:has(.fa-check)',
    },
}


class VtopStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    AWAITING_CREDENTIALS = "awaiting_credentials"
    AWAITING_QR = "awaiting_qr"
    CLICKING_LOGIN = "clicking_login"
    LOGGED_IN = "logged_in"
    NAVIGATING = "navigating"
    FILLING_OBRA = "filling_obra"
    FILLING_COORDS = "filling_coords"
    FILLING_CADASTRO = "filling_cadastro"
    UPLOADING = "uploading"
    SAVING = "saving"
    VALIDATING = "validating"
    DONE = "done"
    ERROR = "error"
    PAUSED = "paused"


@dataclass
class VtopJobState:
    cdoi_id: Optional[int] = None
    status: VtopStatus = VtopStatus.IDLE
    message: str = ""
    step: str = ""
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: str = ""
    session_valid: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)
    qr_image: str = ""

    def to_dict(self) -> Dict[str, Any]:
        extras = dict(self.extras or {})
        extras.pop("vtop_senha", None)
        extras.pop("senha", None)
        extras.pop("_vtop_senha_runtime", None)
        return {
            "cdoi_id": self.cdoi_id,
            "status": self.status.value,
            "message": self.message,
            "step": self.step,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "session_valid": self.session_valid,
            "extras": extras,
            "needs_vtop_login": self.error == "needs_vtop_login",
            "qr_image": self.qr_image if self.status == VtopStatus.AWAITING_QR else "",
        }


def _norm_nome_bloco(nome: str) -> str:
    """Normaliza nome de bloco/complemento para comparação (BLOCO 05 → BLOCO 5)."""
    s = (nome or "").strip().upper()
    # Grade Brownfield trunca com reticências (ADMINISTRA… / ADMINISTRA...)
    s = s.replace("…", "").replace("...", "").strip()
    m = re.match(r"BLOCO\s*0*(\d+)$", s)
    if m:
        return f"BLOCO {int(m.group(1))}"
    return (
        s.replace("Ç", "C")
        .replace("Ã", "A")
        .replace("Á", "A")
        .replace("Â", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Õ", "O")
        .replace("Ú", "U")
    )


def _bloco_equiv(a: str, b: str) -> bool:
    """True se os nomes representarem o mesmo complemento (tolera truncamento não-numérico)."""
    na, nb = _norm_nome_bloco(a), _norm_nome_bloco(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Nunca confundir BLOCO 1 com BLOCO 10 (startswith quebraria)
    if na.startswith("BLOCO ") or nb.startswith("BLOCO "):
        return False
    # ADMINISTRAÇÃO / ADMINISTRATIVO / ADMINISTRA… são o mesmo complemento de negócio
    if na.startswith("ADMINISTRA") and nb.startswith("ADMINISTRA"):
        return True
    # Truncado na lista (não numérico): PREFIX ≈ PREFIXO_LONGO
    curto, longo = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(curto) >= 6 and longo.startswith(curto):
        return True
    return False


def vtop_criar_permitido(payload: Optional[Dict[str, Any]] = None) -> bool:
    """
    Criação liberada por padrão.

    Anti-duplicação NÃO é esta flag — é o inventário Brownfield
    (mesmo logradouro+número+complemento → reusa, não cria).

    Bloqueio só se VTOP_BLOQUEAR_CRIAR_OBRA=true ou VTOP_PERMITIR_CRIAR_OBRA=false.
    """
    if bool(getattr(settings, "VTOP_BLOQUEAR_CRIAR_OBRA", False)):
        return False
    if not bool(getattr(settings, "VTOP_PERMITIR_CRIAR_OBRA", True)):
        return False
    # payload.permitir_criar=false explícito pode bloquear uma requisição
    if payload is not None and "permitir_criar" in payload and not payload.get("permitir_criar"):
        return False
    return True


_TIPOS_LOGRADOURO = {
    "RUA", "R", "AVENIDA", "AV", "ALAMEDA", "AL", "TRAVESSA", "TV", "PRACA", "PCA",
    "ESTRADA", "EST", "RODOVIA", "ROD", "BECO", "VIA", "LARGO",
}
_PALAVRAS_VAZIAS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _norm_texto(s: str) -> str:
    s = (s or "").replace("…", " ").replace("...", " ")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _chave_logradouro(s: str) -> str:
    palavras = _norm_texto(s).split()
    while palavras and palavras[0] in _TIPOS_LOGRADOURO:
        palavras.pop(0)
    return " ".join(p for p in palavras if p not in _PALAVRAS_VAZIAS)


def logradouro_equivalente(logradouro_cdoi: str, logradouro_grade: str) -> bool:
    """Compara ignorando tipo (Rua/Av), acentos e preposições; tolera nome truncado na grade."""
    a, b = _chave_logradouro(logradouro_cdoi), _chave_logradouro(logradouro_grade)
    if not a or not b:
        return False
    if a == b:
        return True
    curto, longo = (a, b) if len(a) <= len(b) else (b, a)
    if len(curto) >= 5 and f" {curto} " in f" {longo} ":
        return True
    # Truncado no meio da palavra ("ALBERT SCHWAI...")
    return len(curto) >= 8 and longo.startswith(curto)


def similaridade_logradouro(logradouro_cdoi: str, logradouro_grade: str) -> float:
    """0–1; compara também o prefixo quando a grade traz o nome truncado."""
    a, b = _chave_logradouro(logradouro_cdoi), _chave_logradouro(logradouro_grade)
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if 8 <= len(b) < len(a):
        ratio = max(ratio, difflib.SequenceMatcher(None, a[: len(b)], b).ratio())
    return ratio


def logradouro_parecido(logradouro_cdoi: str, logradouro_grade: str) -> bool:
    """Grafia diferente do mesmo nome (ex.: Schwaitzer × Schweitzer) — não é equivalente."""
    if logradouro_equivalente(logradouro_cdoi, logradouro_grade):
        return False
    return similaridade_logradouro(logradouro_cdoi, logradouro_grade) >= LOGRADOURO_SIMILARIDADE_MIN


def numero_equivalente(numero_cdoi: str, numero_grade: str) -> bool:
    """'389' bate com '389/405'; sem número no CDOI não restringe."""
    alvo = {str(int(x)) for x in re.findall(r"\d+", numero_cdoi or "")}
    if not alvo:
        return True
    partes = {str(int(x)) for x in re.findall(r"\d+", numero_grade or "")}
    return bool(alvo & partes)


def linha_bate_endereco(row: Dict[str, Any], logradouro: str, numero: str) -> bool:
    """Linha da grade Brownfield pertence ao endereço do CDOI?"""
    grade_log = str(row.get("logradouro") or "")
    if grade_log:
        return logradouro_equivalente(logradouro, grade_log) and numero_equivalente(
            numero, str(row.get("numero") or "")
        )
    # Sem colunas identificadas: procura no texto da linha inteira
    joined = str(row.get("joined") or "")
    palavras = _chave_logradouro(logradouro).split()
    if palavras and palavras[-1] not in _norm_texto(joined):
        return False
    return not numero or str(numero).strip() in joined


def complemento_da_linha(row: Dict[str, Any]) -> str:
    """Complemento reconhecido (BLOCO/PORTARIA/ADMINISTRAÇÃO/GARAGEM) ou ''."""
    candidatos = [str(row.get("comp") or "")] + [str(t) for t in (row.get("tds") or [])]
    for txt in candidatos:
        u = txt.upper().strip()
        if u.startswith("BLOCO") or "PORTARIA" in u or "ADMINISTRA" in u or "GARAGEM" in u:
            return txt.strip()
    return ""


BROWNFIELD_DIAG_JS = """() => ({
  url: location.href,
  pesquisaObras: typeof pesquisaObras === 'function',
  sel_datas: !!document.getElementById('sel_datas'),
  mg: !!document.querySelector("input[value='MG']"),
  jquery: !!window.jQuery,
  datatables: !!(window.jQuery && jQuery.fn.dataTable),
  dados: !!document.getElementById('dados'),
  readyState: document.readyState,
})"""

BROWNFIELD_PESQUISAR_JS = """() => {
  const mg = document.querySelector("input[value='MG']");
  if (mg) { mg.disabled = false; if (!mg.checked) mg.click(); }
  const sel = document.getElementById('sel_datas');
  if (sel && window.jQuery) window.jQuery(sel).val('T').trigger('change');
  const dados = document.getElementById('dados');
  if (dados) dados.innerHTML = '';
  const b = document.getElementById('b_pesquisa');
  if (b) b.disabled = false;
  pesquisaObras();
}"""

BROWNFIELD_EXIBIR_TUDO_JS = """() => {
  const nome = (typeof nome_tabela !== 'undefined' && nome_tabela) ? nome_tabela : 'dados_obras';
  if (!window.jQuery || !jQuery.fn.dataTable || !jQuery.fn.dataTable.isDataTable('#' + nome)) return -1;
  const t = jQuery('#' + nome).DataTable();
  t.search('').columns().search('').page.len(-1).draw();
  return t.rows().count();
}"""


SALVAR_OBRA_MODAL_ABERTO_JS = """() => {
  const b = document.getElementById('b_criar_obra');
  return !!(b && b.offsetParent !== null);
}"""

SALVAR_OBRA_MENSAGENS_JS = """() => {
  const sels = ['#messages', '.alert', '.swal2-html-container', '.swal2-title', '.toast-message',
                '.modal .text-danger', '.invalid-feedback', 'label.error', '.bootbox-body', '.msg_erro'];
  const out = [];
  for (const s of sels) {
    document.querySelectorAll(s).forEach(el => {
      const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t && el.offsetParent !== null && !out.includes(t)) out.push(t);
    });
  }
  return out.join(' | ').slice(0, 300);
}"""

OBRA_CAMPOS_VAZIOS_JS = """() => {
  const b = document.getElementById('b_criar_obra');
  const root = (b && (b.closest('.modal') || b.closest('form'))) || document;
  const vazios = [], obrigatorios = [];
  root.querySelectorAll('input, select, textarea').forEach(el => {
    const tipo = (el.type || '').toLowerCase();
    if (['hidden', 'button', 'submit', 'checkbox', 'radio', 'file'].includes(tipo)) return;
    if (el.offsetParent === null || el.disabled) return;
    if ((el.value || '').trim() !== '') return;
    const nome = el.id || el.name || '?';
    vazios.push(nome);
    const lbl = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
    const pai = el.parentElement;
    // Texto do pai só vale se ele envolver apenas este campo (senão herda o '*' de outros)
    const paiSo = pai && pai.querySelectorAll('input, select, textarea').length === 1;
    const txtLbl = (lbl && lbl.innerText) || (paiSo ? pai.innerText : '') || '';
    if (el.required || el.getAttribute('aria-required') === 'true' ||
        /obrig|required/i.test(el.className || '') || txtLbl.includes('*')) {
      obrigatorios.push(nome);
    }
  });
  return {vazios, obrigatorios};
}"""


def obras_do_complemento(mapa: Dict[str, List[Dict[str, Any]]], complemento: str) -> List[str]:
    """Ids (sem repetição) das obras do inventário com o mesmo complemento."""
    ids: List[str] = []
    for chave, itens in (mapa or {}).items():
        for item in itens:
            if _bloco_equiv(chave, complemento) or _bloco_equiv(str(item.get("complemento") or ""), complemento):
                oid = str(item.get("id") or "").strip()
                if oid and oid not in ids:
                    ids.append(oid)
    return ids


def brownfield_pronta(diag: Dict[str, Any]) -> bool:
    """Tela Brownfield (fi=2) carregada o suficiente para pesquisar."""
    diag = diag or {}
    return (
        "fi=2" in str(diag.get("url") or "")
        and bool(diag.get("pesquisaObras"))
        and bool(diag.get("sel_datas"))
        and bool(diag.get("mg"))
    )


def motivo_bloqueio_inventario(meta: Dict[str, Any], total_com_complemento: int) -> str:
    """
    Complemento não achado na grade: decide se é seguro criar obra nova.
    Retorna a mensagem de bloqueio, ou "" quando pode criar.
    """
    meta = meta or {}
    fim = meta.get("fim") or ""
    linhas_endereco = int(meta.get("linhas_endereco") or 0)
    paginas = int(meta.get("paginas") or 0)
    sem_complemento = linhas_endereco - total_com_complemento
    parecidos = [str(p) for p in (meta.get("logradouros_parecidos") or []) if p]
    if parecidos:
        return (
            f"A grade tem obra(s) no mesmo número em logradouro com grafia parecida: "
            f"{', '.join(parecidos[:3])} — confira o endereço do CDOI; não é seguro criar (poderia duplicar)."
        )
    if total_com_complemento > 0 and sem_complemento > 0:
        # Ex.: TORRE 1 no mesmo endereço pode ser o mesmo prédio do BLOCO 1 → duplicaria
        return (
            f"Há {sem_complemento} obra(s) neste endereço com complemento não reconhecido "
            "(fora de BLOCO/PORTARIA/ADMINISTRAÇÃO/GARAGEM) — não é seguro criar."
        )
    if total_com_complemento > 0:
        if fim == "fim_lista":
            return ""
        # Lista não chegou ao fim: o bloco pode estar numa página não lida → duplicaria a obra
        return (
            f"Busca parou em {paginas} página(s) sem chegar ao fim da lista "
            f"({'limite de páginas' if fim == 'limite' else 'paginação não confirmada'}); "
            f"o endereço tem {total_com_complemento} obra(s), mas o bloco não foi encontrado — "
            "não é seguro criar (poderia duplicar)."
        )
    if linhas_endereco > 0:
        return (
            f"Há {linhas_endereco} obra(s) neste endereço sem complemento reconhecível "
            "(BLOCO/PORTARIA/ADMINISTRAÇÃO/GARAGEM) — não é seguro criar."
        )
    if fim == "fim_lista":
        return ""
    if fim == "limite":
        return (
            f"Busca atingiu o limite de {paginas} páginas sem encontrar o endereço — "
            "não é seguro criar (o endereço pode estar nas páginas seguintes)."
        )
    if fim == "sem_resultados":
        # Se a busca retornou vazio, provavelmente é um endereço totalmente novo, permitimos criar.
        return ""
    return (
        "A paginação do inventário Brownfield não avançou e não foi possível confirmar o fim da lista — "
        "não é seguro criar. Tente de novo."
    )


def ler_etapa_obra_page(page) -> Optional[int]:
    """Lê obra.etapa no JS da página; None se indisponível."""
    try:
        etapa = page.evaluate(
            "() => (typeof obra !== 'undefined' && obra && obra.etapa != null ? obra.etapa : null)"
        )
        if etapa is None:
            return None
        return int(etapa)
    except Exception:
        return None



def persistir_vtop_obra_bloco(
    cdoi_id: Optional[int],
    nome_bloco: str,
    obra_id: str,
    etapa: Optional[int] = None,
    *,
    sobrescrever: bool = False,
) -> bool:
    """
    Grava o vínculo bloco → obra_id no BlocoVertical.
    Por padrão NÃO sobrescreve obra_id diferente (anti-duplicação / lista truncada).
    """
    if not cdoi_id or not obra_id or not nome_bloco:
        return False
    try:
        from django.utils import timezone
        from tickets.models import BlocoVertical

        qs = BlocoVertical.objects.filter(solicitacao_id=int(cdoi_id))
        bloco = None
        for b in qs:
            if _bloco_equiv(b.nome_bloco, nome_bloco):
                bloco = b
                break
        if bloco is None:
            logger.warning(
                "[VTOP] Bloco '%s' não encontrado no CDOI %s para gravar obra_id=%s",
                nome_bloco,
                cdoi_id,
                obra_id,
            )
            return False
        atual = (bloco.vtop_obra_id or "").strip()
        novo = str(obra_id).strip()
        if atual and atual != novo and not sobrescrever:
            logger.warning(
                "[VTOP] Mantém obra_id=%s em '%s' (ignorou %s da lista) — use sobrescrever=True se for intencional",
                atual,
                bloco.nome_bloco,
                novo,
            )
            # Ainda atualiza etapa se veio
            if etapa is not None:
                try:
                    bloco.vtop_etapa = int(etapa)
                    bloco.vtop_sincronizado_em = timezone.now()
                    bloco.save(update_fields=["vtop_etapa", "vtop_sincronizado_em"])
                except (TypeError, ValueError):
                    pass
            return False
        bloco.vtop_obra_id = novo
        if etapa is not None:
            try:
                bloco.vtop_etapa = int(etapa)
            except (TypeError, ValueError):
                pass
        bloco.vtop_sincronizado_em = timezone.now()
        bloco.save(
            update_fields=["vtop_obra_id", "vtop_etapa", "vtop_sincronizado_em"]
        )
        logger.info(
            "[VTOP] Vínculo gravado CDOI=%s bloco=%s obra_id=%s etapa=%s",
            cdoi_id,
            bloco.nome_bloco,
            novo,
            etapa,
        )
        return True
    except Exception:
        logger.exception(
            "[VTOP] Falha ao gravar obra_id=%s no CDOI %s / bloco %s",
            obra_id,
            cdoi_id,
            nome_bloco,
        )
        return False


def _anexo_local_ou_url(campo) -> str:
    """Caminho em disco (FileSystemStorage) ou URL do storage remoto (R2) do FileField."""
    if not campo:
        return ""
    try:
        return campo.path
    except (NotImplementedError, ValueError, AttributeError):
        pass
    try:
        return campo.url
    except Exception:
        return ""


def codigo_sap_do_acionamento(cdoi) -> str:
    """Código SAP = código do PDV do acionamento (parceiro, PDV do contato ou conta PDV do criador)."""
    candidatos = [
        getattr(cdoi, "parceiro", None),
        getattr(getattr(cdoi, "contato", None), "parceiro", None),
    ]
    try:
        candidatos.append(cdoi.criado_por.parceiro_conta)
    except Exception:
        pass
    for pdv in candidatos:
        codigo = (getattr(pdv, "codigo_pdv", "") or "").strip()
        if codigo:
            return codigo
    return ""


def montar_payload_vertical(cdoi) -> Dict[str, Any]:
    """Converte SolicitacaoVertical (+ blocos) no dict base (ainda sem escolher 1 bloco)."""
    blocos = list(cdoi.blocos.all().order_by("nome_bloco"))
    blocos_data = [
        {
            "nome": b.nome_bloco,
            "andares": int(b.andares or 0),
            "aptos": int(b.unidades_por_andar or 0),
            "total": int(b.total_hps_bloco or (int(b.andares or 0) * int(b.unidades_por_andar or 0))),
            "obra_id": (b.vtop_obra_id or "").strip(),
            "vtop_etapa": b.vtop_etapa,
        }
        for b in blocos
    ]
    max_andares = max((b["andares"] for b in blocos_data), default=0)

    partes_caract: List[str] = []
    for b in blocos_data:
        partes_caract.append(
            f"{b['nome']}: {b['andares']} andares, {b['aptos']} ums/andar "
            f"({b['total']} HPs)"
        )
    infra = (cdoi.infraestrutura_tipo or "").strip()
    if infra:
        partes_caract.append(f"Infraestrutura: {infra}")
    partes_caract.append(f"Shaft/DG: {'sim' if cdoi.possui_shaft_dg else 'não'}")

    return {
        "cdoi_id": cdoi.id,
        "nome_condominio": (cdoi.nome_condominio or "").strip(),
        "nome_sindico": (cdoi.nome_sindico or "").strip(),
        "contato": re.sub(r"\D", "", cdoi.contato_sindico or ""),
        "cep": re.sub(r"\D", "", cdoi.cep or ""),
        "logradouro": (cdoi.logradouro or "").strip(),
        "numero": (cdoi.numero or "").strip(),
        "bairro": (cdoi.bairro or "").strip(),
        "cidade": (cdoi.cidade or "").strip(),
        "uf": (cdoi.uf or "").strip().upper(),
        "latitude": (cdoi.latitude or "").strip(),
        "longitude": (cdoi.longitude or "").strip(),
        # Totais do condomínio (referência). Por obra use payload_para_bloco().
        "total_hps_condominio": int(cdoi.total_hps or 0),
        "pre_venda": int(cdoi.pre_venda_minima or 0),
        "qtd_blocos": len(blocos_data),
        "max_andares": max_andares,
        "caracteristicas": "; ".join(partes_caract),
        "link_carta": _anexo_local_ou_url(cdoi.arquivo_carta),
        "link_fachada": _anexo_local_ou_url(cdoi.arquivo_fachada),
        "codigo_sap": codigo_sap_do_acionamento(cdoi),
        "cod_survey": "",
        "estacao": "",
        "celula": "",
        "cdoi_codigo": str(cdoi.id),
        "blocos": blocos_data,
        # Campos da obra atual — vazios até escolher o bloco
        "bloco_nome": "",
        "complemento": "",
        "total_hps": 0,
        "andares": 0,
        "aptos": 0,
    }


def payload_para_bloco(payload_base: Dict[str, Any], nome_bloco: str) -> Dict[str, Any]:
    """
    Monta payload de UMA obra SmartRiser a partir de um bloco do CDOI.

    Regra de negócio:
      - Cada nome de bloco (complemento) = uma obra separada
      - QUANTIDADE UMS = andares × aptos do bloco (ou total do bloco)
      - NÃO concatenar todos os blocos no complemento
    """
    alvo = (nome_bloco or "").strip().upper()
    escolhido = None
    for b in payload_base.get("blocos") or []:
        nome = str(b.get("nome") or "").strip()
        if nome.upper() == alvo:
            escolhido = b
            break
    if not escolhido:
        # tolerância: "BLOCO 5" == "BLOCO 05"
        m = re.match(r"BLOCO\s*0*(\d+)$", alvo)
        if m:
            num = m.group(1)
            for b in payload_base.get("blocos") or []:
                nome = str(b.get("nome") or "").strip().upper()
                m2 = re.match(r"BLOCO\s*0*(\d+)$", nome)
                if m2 and m2.group(1) == num:
                    escolhido = b
                    break
    if not escolhido:
        raise ValueError(f"Bloco '{nome_bloco}' não encontrado no payload CDOI.")

    andares = int(escolhido.get("andares") or 0)
    aptos = int(escolhido.get("aptos") or 0)
    total = int(escolhido.get("total") or 0) or (andares * aptos)
    nome_oficial = str(escolhido.get("nome") or nome_bloco).strip()

    out = dict(payload_base)
    out["bloco_nome"] = nome_oficial
    out["complemento"] = nome_oficial  # = nome do bloco no Gestão CDOI
    out["andares"] = andares
    out["aptos"] = aptos
    out["total_hps"] = total
    # Reabre obra já vinculada em vez de criar duplicata com o mesmo complemento
    obra_id = str(escolhido.get("obra_id") or "").strip()
    if obra_id:
        out["obra_id"] = obra_id
    elif out.get("obra_id"):
        # limpa obra_id de outro bloco se veio no base por engano
        out.pop("obra_id", None)
    # Características desta obra (= 1 bloco), não o condomínio inteiro
    out["caracteristicas"] = (
        f"{nome_oficial}: {andares} andares, {aptos} ums/andar ({total} HPs)"
    )
    # Pré-venda da obra = 18% (ceil) dos HPs do bloco — NÃO usar o total do condomínio
    out["pre_venda"] = calcular_pre_venda_bloco(total)
    return out


def baixar_anexo_temporario(url: str, prefix: str = "vtop_") -> Optional[str]:
    """
    Obtém arquivo local para upload.
    Aceita caminho local (Windows/Unix), file:// ou URL HTTP(S).
    """
    if not url:
        return None
    # Caminho local direto
    local = url
    if url.lower().startswith("file:"):
        local = urlparse(url).path
        if os.name == "nt" and local.startswith("/"):
            local = local.lstrip("/")
    if os.path.isfile(local):
        return local
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        suffix = Path(urlparse(url).path).suffix or ".bin"
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(resp.content)
        return path
    except Exception as exc:
        logger.exception("[VTOP] Falha ao baixar anexo %s: %s", url, exc)
        return None


class VtopSmartRiserService:
    """
    Singleton por processo: mantém o browser aberto entre passos.

    Uso típico (CDOI):
      svc.iniciar(cdoi_id, payload)     # abre browser; se precisa login → awaiting_qr
      svc.get_state()                   # polling da UI (traz qr_image para exibir no CDOI)
      # usuário escaneia com o app V.tal Pass → thread detecta o redirect,
      # salva storage e segue o fluxo
      svc.signal_senha_pronta()         # alternativa local: senha digitada na janela visível
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._credentials_event = threading.Event()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self.state = VtopJobState()

        self.playwright = None
        # Playwright sync só pode ser usado/fechado pela thread que o abriu
        self._browser_thread_id: Optional[int] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._temp_files: List[str] = []
        self._payload_atual: Dict[str, Any] = {}
        self._inventario_meta: Dict[str, Any] = {}

    # ------------------------------------------------------------------ status
    def _set(
        self,
        status: VtopStatus,
        message: str = "",
        step: str = "",
        error: str = "",
        **extras: Any,
    ) -> None:
        self.state.status = status
        self.state.message = message
        if step:
            self.state.step = step
        if error:
            self.state.error = error
        if extras:
            self.state.extras.update(extras)
        self.state.updated_at = datetime.now().isoformat(timespec="seconds")
        self.state.session_valid = self._storage_exists() and status not in (
            VtopStatus.AWAITING_CREDENTIALS,
            VtopStatus.AWAITING_QR,
            VtopStatus.CLICKING_LOGIN,
            VtopStatus.ERROR,
        )
        logger.info("[VTOP] %s | %s | %s", status.value, step or "-", message)
        self._publicar_estado()

    def _publicar_estado(self) -> None:
        self.state.updated_at = datetime.now().isoformat(timespec="seconds")
        try:
            _db_op(cache.set, CACHE_KEY_ESTADO, self.state.to_dict(), CACHE_TTL_S)
        except Exception:
            logger.exception("[VTOP] Falha ao publicar estado no cache")

    @staticmethod
    def _estado_cache() -> Optional[Dict[str, Any]]:
        try:
            return _db_op(cache.get, CACHE_KEY_ESTADO)
        except Exception:
            logger.exception("[VTOP] Falha ao ler estado do cache")
            return None

    @staticmethod
    def _estado_ativo(estado: Optional[Dict[str, Any]]) -> bool:
        if not estado or estado.get("status") not in STATUS_ATIVOS:
            return False
        try:
            atualizado = datetime.fromisoformat(estado.get("updated_at") or "")
        except ValueError:
            return False
        return (datetime.now() - atualizado).total_seconds() < ESTADO_ORFAO_APOS_S

    @staticmethod
    def _enviar_comando(comando: str) -> None:
        try:
            _db_op(cache.set, CACHE_KEY_COMANDO, comando, CACHE_TTL_S)
        except Exception:
            logger.exception("[VTOP] Falha ao enviar comando %s", comando)

    def _processar_comandos(self) -> None:
        """Aplica comandos vindos de outro worker (fechar / senha pronta)."""
        try:
            comando = _db_op(cache.get, CACHE_KEY_COMANDO)
            if not comando:
                return
            _db_op(cache.delete, CACHE_KEY_COMANDO)
        except Exception:
            return
        if comando == "stop":
            self._stop_event.set()
        elif comando == "senha_pronta":
            self._credentials_event.set()

    def _job_local_ativo(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            if self._job_local_ativo():
                self.state.session_valid = self._storage_exists()
                return self.state.to_dict()
        estado = self._estado_cache()
        if estado:
            estado = dict(estado)
            estado["session_valid"] = self._storage_exists()
            if estado.get("status") in STATUS_ATIVOS and not self._estado_ativo(estado):
                estado.update(
                    status=VtopStatus.ERROR.value,
                    message="Automação interrompida (servidor reiniciado ou travado). Inicie novamente.",
                    error="orphan_job",
                    qr_image="",
                )
            return estado
        with self._lock:
            self.state.session_valid = self._storage_exists()
            return self.state.to_dict()

    def _storage_exists(self) -> bool:
        path = _storage_state_path()
        return os.path.isfile(path) and os.path.getsize(path) > 50

    # -------------------------------------------------------------- API pública
    def iniciar(
        self,
        cdoi_id: int,
        payload: Dict[str, Any],
        *,
        forcar_login: bool = False,
        pausar_apos: Optional[str] = None,
        somente_ate: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Inicia a automação em thread dedicada (Playwright exige mesma thread).

        pausar_apos / somente_ate: nome do passo (ex.: 'portal', 'brownfield',
        'obra_modal') — útil para mapear sem concluir o fluxo todo.
        """
        with self._lock:
            if self._job_local_ativo():
                return {
                    "ok": False,
                    "error": "Já existe uma automação V.top em andamento.",
                    "state": self.state.to_dict(),
                }
            estado_outro_worker = self._estado_cache()
            if self._estado_ativo(estado_outro_worker):
                return {
                    "ok": False,
                    "error": "Já existe uma automação V.top em andamento.",
                    "state": estado_outro_worker,
                }
            if not HAS_PLAYWRIGHT:
                return {"ok": False, "error": "Playwright não instalado neste ambiente."}

            try:
                _db_op(cache.delete, CACHE_KEY_COMANDO)
            except Exception:
                pass
            self._credentials_event.clear()
            self._stop_event.clear()
            self.state = VtopJobState(
                cdoi_id=cdoi_id,
                status=VtopStatus.STARTING,
                message="Iniciando navegador…",
                started_at=datetime.now().isoformat(timespec="seconds"),
                updated_at=datetime.now().isoformat(timespec="seconds"),
                extras={
                    "forcar_login": forcar_login,
                    "pausar_apos": pausar_apos,
                    "somente_ate": somente_ate,
                },
            )
            self._publicar_estado()

            self._worker = threading.Thread(
                target=self._run_job,
                args=(payload, forcar_login, pausar_apos, somente_ate),
                name=f"vtop-cdoi-{cdoi_id}",
                daemon=True,
            )
            self._worker.start()
            return {"ok": True, "state": self.state.to_dict()}

    def signal_senha_pronta(self) -> Dict[str, Any]:
        """Chamado pelo botão 'Já coloquei a senha' no Gestão CDOI."""
        aguardando = (VtopStatus.AWAITING_CREDENTIALS.value, VtopStatus.AWAITING_QR.value)
        with self._lock:
            if self._job_local_ativo():
                if self.state.status.value not in aguardando:
                    return {
                        "ok": False,
                        "error": (
                            f"Não estamos aguardando senha (status={self.state.status.value}). "
                            "Inicie a automação primeiro."
                        ),
                        "state": self.state.to_dict(),
                    }
                self._credentials_event.set()
                return {"ok": True, "state": self.state.to_dict()}

        estado = self._estado_cache()
        if not self._estado_ativo(estado) or estado.get("status") not in aguardando:
            return {
                "ok": False,
                "error": "Não estamos aguardando login. Inicie a automação primeiro.",
                "state": estado or self.state.to_dict(),
            }
        self._enviar_comando("senha_pronta")
        return {"ok": True, "state": estado}

    def fechar_navegador(self, *, manter_sessao: bool = True) -> Dict[str, Any]:
        """Fecha o browser. Por padrão NÃO apaga o storage_state (não desloga)."""
        self._enviar_comando("stop")
        self._stop_event.set()
        with self._lock:
            # Job ativo: só sinaliza; a própria thread do job fecha o navegador
            if not self._job_local_ativo():
                self._cleanup_browser(salvar_sessao=manter_sessao)
            self._set(VtopStatus.IDLE, "Navegador fechado (sessão preservada)." if manter_sessao else "Navegador fechado.")
            return {"ok": True, "state": self.state.to_dict()}

    def invalidar_sessao(self) -> Dict[str, Any]:
        """Só use se a sessão estiver corrompida. Remove o storage_state."""
        path = _storage_state_path()
        try:
            if os.path.exists(path):
                os.remove(path)
            return {"ok": True, "message": "Sessão V.top invalidada. Será necessário login manual."}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    # --------------------------------------------------------------- worker
    def _run_job(
        self,
        payload: Dict[str, Any],
        forcar_login: bool,
        pausar_apos: Optional[str],
        somente_ate: Optional[str],
    ) -> None:
        logado = False
        try:
            # Senha só na memória desta execução — nunca vai para extras/logs
            payload = dict(payload or {})
            _senha_runtime = str(payload.pop("vtop_senha", "") or "")
            self._payload_atual = dict(payload)
            if _senha_runtime:
                self._payload_atual["_vtop_senha_runtime"] = _senha_runtime
            self._abrir_browser(forcar_login=forcar_login)
            if not self._garantir_logado(forcar_login=forcar_login):
                return
            logado = True
            self._payload_atual.pop("_vtop_senha_runtime", None)

            # Teste seguro: valida login e persiste storage_state sem navegar no SmartRiser
            if (somente_ate or "").lower() == "login":
                self._salvar_storage()
                self._set(
                    VtopStatus.DONE,
                    "Login OK — sessão salva em .playwright_vtop_state.json (sem deslogar).",
                    step="login",
                )
                return

            # ------------------------------------------------------------------
            # Fluxo padrão (produção):
            #   1) Inventário Brownfield no endereço
            #   2) Se já existir o MESMO complemento → reusa (não duplica)
            #   3) Senão → cria obra nova → Cadastro → salvar → validar
            #
            # Atalho: obra_id explícito + forcar_obra_id → reabre direto (sem lista).
            # ------------------------------------------------------------------
            obra_id_forcado = ""
            if payload.get("forcar_obra_id") and str(payload.get("obra_id") or "").strip():
                obra_id_forcado = str(payload.get("obra_id")).strip()

            if obra_id_forcado:
                payload["obra_id"] = obra_id_forcado
                self._payload_atual = dict(payload)
                passos = [
                    ("abrir_obra", lambda: self._passo_abrir_obra_existente(obra_id_forcado)),
                    ("concluir_cadastro", lambda: self._passo_concluir_cadastro_se_preciso(payload)),
                ]
            else:
                # Preferência do banco entra no inventário como "preferido", não pula a checagem
                preferido_db = self._resolver_obra_id_seguro(payload)
                if preferido_db and not payload.get("obra_id"):
                    payload["obra_id"] = preferido_db
                self._payload_atual = dict(payload)
                passos = [
                    ("portal", lambda: self._passo_portal()),
                    ("smartriser", lambda: self._passo_abrir_smartriser()),
                    ("brownfield", lambda: self._passo_brownfield()),
                    ("localizar", lambda: self._passo_tentar_reusar_obra_lista(payload)),
                    ("obra_modal", lambda: self._passo_abrir_modal_obra_se_preciso(payload)),
                    ("preencher_obra", lambda: self._passo_preencher_obra_se_preciso(payload)),
                    ("coords", lambda: self._passo_coords_se_preciso(payload)),
                    ("salvar_obra", lambda: self._passo_salvar_obra_modal_se_preciso(payload)),
                    ("coords_pos_salvar", lambda: self._passo_coords_pos_salvar_se_preciso(payload)),
                    ("concluir_cadastro", lambda: self._passo_concluir_cadastro_se_preciso(payload)),
                ]

            for nome, fn in passos:
                self._processar_comandos()
                if self._stop_event.is_set():
                    self._cleanup_browser(salvar_sessao=True)
                    self._set(VtopStatus.IDLE, "Interrompido pelo usuário.", step=nome)
                    return
                fn()
                if pausar_apos == nome:
                    self._set(
                        VtopStatus.PAUSED,
                        f"Pausado após passo '{nome}' para mapeamento.",
                        step=nome,
                    )
                    return
                if somente_ate == nome:
                    self._set(
                        VtopStatus.DONE,
                        f"Fluxo executado até '{nome}'.",
                        step=nome,
                    )
                    return

            self._salvar_storage()
            if not str(self.state.extras.get("obra_id") or "").strip():
                self._set(
                    VtopStatus.ERROR,
                    "Fluxo terminou sem obra_id confirmado — confira na V.tal antes de tentar de novo.",
                    step="fim",
                    error="sem_obra_id",
                )
                return
            self._set(VtopStatus.DONE, "Fluxo SmartRiser concluído.", step="fim")
        except Exception as exc:
            logger.exception("[VTOP] Erro na automação: %s", exc)
            self._set(VtopStatus.ERROR, "Falha na automação.", error=str(exc))
        finally:
            self._limpar_temp_files()
            # Local (visível) mantém o browser aberto para inspeção. Em headless ninguém
            # inspeciona e, após esta thread sair, o Playwright não pode mais ser fechado.
            if _headless() and self.state.status != VtopStatus.PAUSED:
                self._cleanup_browser(salvar_sessao=logado)

    # ----------------------------------------------------------- browser/sessão
    def _abrir_browser(self, *, forcar_login: bool) -> None:
        self._set(VtopStatus.STARTING, "Abrindo Chromium…", step="browser")
        self._dialog_handler_installed = False
        # Materializa sessão do env (produção) antes de abrir o contexto
        if not forcar_login:
            _garantir_storage_state_arquivo()
        self.playwright = sync_playwright().start()
        self._browser_thread_id = threading.get_ident()
        launch_opts: Dict[str, Any] = {
            "headless": _headless(),
            "slow_mo": 0 if _headless() else 80,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        self.browser = self.playwright.chromium.launch(**launch_opts)

        storage = None if forcar_login else (
            _storage_state_path() if self._storage_exists() else None
        )
        self.context = self.browser.new_context(
            storage_state=storage,
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
        )
        self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(DEFAULT_TIMEOUT_MS)

    def _salvar_storage(self) -> None:
        if self.context:
            path = _storage_state_path()
            self.context.storage_state(path=path)
            logger.info("[VTOP] Sessão salva em %s", path)
            self.state.session_valid = True

    def _cleanup_browser(self, *, salvar_sessao: bool) -> None:
        dono = self._browser_thread_id
        if dono is not None and dono != threading.get_ident():
            # Outra thread: chamar o Playwright gera greenlet.error e não fecha nada
            logger.warning("[VTOP] Cleanup ignorado fora da thread do navegador (thread encerrada)")
            self.page = self.context = self.browser = None
            self.playwright = None
            self._browser_thread_id = None
            self._limpar_temp_files()
            return
        try:
            if salvar_sessao and self.context:
                self._salvar_storage()
        except Exception:
            logger.exception("[VTOP] Falha ao salvar sessão no cleanup")
        for attr in ("page", "context", "browser"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
            setattr(self, attr, None)
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self._browser_thread_id = None
        self._limpar_temp_files()

    def _limpar_temp_files(self) -> None:
        for path in self._temp_files:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._temp_files.clear()

    def _esta_logado(self) -> bool:
        assert self.page is not None
        url = (self.page.url or "").lower()
        if "login.vtal.com" in url or "nidp" in url:
            return False
        # Exige evidência real de portal autenticado (evita falso positivo só pela URL)
        try:
            if self.page.locator("text=/Olá\\s+[A-Za-zÀ-ú]/i").count() > 0:
                return True
            if self.page.locator("text=Bem vindo ao portal V.top").count() > 0:
                return True
            if self.page.locator("text=SmartRiser - Rede Inteligente Vertical").count() > 0:
                return True
        except Exception:
            pass
        return False

    def _garantir_logado(self, *, forcar_login: bool) -> bool:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Abrindo V.top…", step="login")
        self.page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
        time.sleep(1.5)

        if not forcar_login and self._esta_logado():
            self._salvar_storage()
            self._set(VtopStatus.LOGGED_IN, "Sessão reutilizada — login não necessário.", step="login")
            return True

        usuario = str((self._payload_atual or {}).get("vtop_usuario") or "").strip()
        senha = str(
            (self._payload_atual or {}).get("_vtop_senha_runtime")
            or (self._payload_atual or {}).get("vtop_senha")
            or ""
        )

        if "login.vtal.com" not in (self.page.url or ""):
            self.page.goto(VTOP_LOGIN_URL, wait_until="domcontentloaded")
            time.sleep(1)

        # Produção (headless) ou local com credenciais do modal → preenche automaticamente
        if usuario and senha:
            if not self._preencher_login_automatico(usuario, senha):
                return False
            # Limpa senha da memória do payload o quanto antes
            if self._payload_atual:
                self._payload_atual.pop("vtop_senha", None)
                self._payload_atual.pop("_vtop_senha_runtime", None)
            return True

        return self._aguardar_login_qr()

    def _ler_qr_code(self) -> Tuple[str, str]:
        """(data URL do QR se visível e conectado, mensagem de erro exibida pela V.tal)."""
        assert self.page is not None
        try:
            dados = self.page.evaluate(
                """() => {
                    const img = document.getElementById('qrcode-access');
                    const lab = document.getElementById('labelStatusConLabel');
                    const msgs = document.getElementById('messages');
                    const aviso = msgs ? (msgs.innerText || '').trim() : '';
                    if (!img || img.offsetParent === null) return ['', aviso];
                    if (lab && /desconectado/i.test(lab.innerText || '')) return ['', aviso];
                    return [(img.getAttribute('src') || '').replace(/\\s+/g, ''), aviso];
                }"""
            )
        except Exception:
            return "", ""
        qr, aviso = (dados or ["", ""])[:2]
        if not str(qr).startswith("data:image/"):
            qr = ""
        return str(qr), str(aviso or "")[:200]

    def _aguardar_login_qr(self) -> bool:
        """
        Deixa a tela de login V.tal aberta e repassa o QR (FAST PASS) para o CDOI.
        Após a leitura no app V.tal Pass, a própria página V.tal envia o formulário e
        redireciona para o V.top — aqui só detectamos a saída de login.vtal.com.
        Local (browser visível) também aceita senha digitada + «Já coloquei a senha».
        """
        assert self.page is not None
        self._credentials_event.clear()
        self.state.qr_image = ""
        self._set(
            VtopStatus.AWAITING_QR,
            "Escaneie o QR Code com o app V.tal Pass para entrar.",
            step="login",
        )
        inicio = time.time()
        ultimo_qr_visto = time.time()
        ultima_publicacao = 0.0

        while time.time() - inicio < LOGIN_WAIT_SECONDS:
            self._processar_comandos()
            if self._stop_event.is_set():
                self.state.qr_image = ""
                self._cleanup_browser(salvar_sessao=False)
                self._set(VtopStatus.IDLE, "Login cancelado pelo usuário.", step="login")
                return False

            if self._credentials_event.is_set():
                self.state.qr_image = ""
                self._clicar_efetuar_login()
                return self._confirmar_login_pos_clique()

            url = (self.page.url or "").lower()
            if "login.vtal.com" not in url and "nidp" not in url:
                self.state.qr_image = ""
                self._set(VtopStatus.CLICKING_LOGIN, "QR Code lido — confirmando login…", step="login")
                return self._confirmar_login_pos_clique(via_qr=True)

            qr, aviso = self._ler_qr_code()
            agora = time.time()
            if qr:
                ultimo_qr_visto = agora
                mensagem = "Escaneie o QR Code com o app V.tal Pass para entrar."
                if aviso:
                    mensagem = f"{mensagem} V.tal: {aviso}"
                if qr != self.state.qr_image or mensagem != self.state.message:
                    self.state.qr_image = qr
                    self.state.message = mensagem
                    self._publicar_estado()
                    ultima_publicacao = agora
            elif agora - ultimo_qr_visto > QR_RECARREGAR_APOS_S:
                logger.info("[VTOP] QR ausente/desconectado há %ss — recarregando login", QR_RECARREGAR_APOS_S)
                self.state.qr_image = ""
                self.state.message = "Gerando novo QR Code…"
                self._publicar_estado()
                try:
                    self.page.goto(VTOP_LOGIN_URL, wait_until="domcontentloaded")
                except Exception:
                    logger.exception("[VTOP] Falha ao recarregar tela de login")
                ultimo_qr_visto = time.time()

            if agora - ultima_publicacao > 30:
                self._publicar_estado()
                ultima_publicacao = agora
            self.page.wait_for_timeout(QR_POLL_MS)

        self.state.qr_image = ""
        self._set(
            VtopStatus.ERROR,
            "Tempo esgotado aguardando a leitura do QR Code.",
            step="login",
            error="timeout_qr",
        )
        return False

    def _preencher_login_automatico(self, usuario: str, senha: str) -> bool:
        """Preenche usuário/senha na tela IdP V.tal (sem logar a senha)."""
        assert self.page is not None
        page = self.page
        self._set(
            VtopStatus.CLICKING_LOGIN,
            "Preenchendo login V.tal com credenciais do modal…",
            step="login",
        )
        try:
            # Campos comuns do NIDP / login corporativo
            user_loc = page.locator(
                'input[type="text"], input[type="email"], input[name*="user" i], '
                'input[id*="user" i], input[name*="Ecom_User" i], input#Ecom_User_ID'
            ).first
            pass_loc = page.locator(
                'input[type="password"], input[name*="pass" i], input[id*="pass" i], '
                'input[name*="Ecom_Password" i], input#Ecom_Password'
            ).first
            user_loc.wait_for(state="visible", timeout=20_000)
            user_loc.fill(usuario)
            pass_loc.fill(senha)
            page.wait_for_timeout(300)
            self._clicar_efetuar_login()
            return self._confirmar_login_pos_clique()
        except Exception as exc:
            logger.exception("[VTOP] Falha ao preencher login automático")
            self._set(
                VtopStatus.ERROR,
                "Não foi possível preencher o login V.tal automaticamente.",
                step="login",
                error=str(exc)[:200],
            )
            return False

    def _aguardar_esta_logado(self, timeout_s: float = LOGIN_CONFIRMAR_S) -> bool:
        """O portal renderiza o 'Olá …' alguns segundos depois do redirect."""
        assert self.page is not None
        fim = time.time() + timeout_s
        while True:
            try:
                if self._esta_logado():
                    return True
            except Exception:
                pass
            if time.time() >= fim:
                return False
            try:
                self.page.wait_for_timeout(1000)
            except Exception:
                time.sleep(1)

    def _confirmar_login_pos_clique(self, *, via_qr: bool = False) -> bool:
        assert self.page is not None
        try:
            self.page.wait_for_url("**/appvtop/**", timeout=90_000)
        except Exception:
            self.page.wait_for_timeout(5000)

        if not self._aguardar_esta_logado():
            self.page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
            self._aguardar_esta_logado(timeout_s=10)

        if not self._esta_logado():
            if via_qr:
                self._set(
                    VtopStatus.ERROR,
                    "Login não confirmado após leitura do QR — gere um novo QR.",
                    step="login",
                    error="login_qr_failed",
                )
            else:
                self._set(
                    VtopStatus.ERROR,
                    "Login não confirmado após EFETUAR LOGIN. Verifique usuário/senha/MFA.",
                    step="login",
                    error="login_failed",
                )
            return False

        self._salvar_storage()
        self._set(VtopStatus.LOGGED_IN, "Login concluído e sessão salva.", step="login")
        return True

    def _clicar_efetuar_login(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.CLICKING_LOGIN, "Clicando em EFETUAR LOGIN…", step="login")
        # Se o usuário já clicou manualmente / MFA / redirect, não falhar
        if self._esta_logado():
            return
        url = (self.page.url or "").lower()
        if "vtop.vtal.com" in url and "login.vtal.com" not in url:
            return

        seletores = [
            'button:has-text("EFETUAR LOGIN")',
            'button:has-text("EFETUAR")',
            'input[type="submit"][value*="EFETUAR" i]',
            'button[type="submit"]',
            'input[type="submit"]',
        ]
        for sel in seletores:
            loc = self.page.locator(sel)
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=5_000)
                    return
            except Exception:
                continue

        # Última tentativa: Enter no campo senha
        try:
            pwd = self.page.locator('input[type="password"]').first
            if pwd.count() > 0 and pwd.is_visible():
                pwd.press("Enter")
                return
        except Exception:
            pass

        # Não explode se o botão sumiu (usuário pode ter logado à mão)
        logger.warning("[VTOP] Botão EFETUAR LOGIN não encontrado — aguardando redirect…")
        self.page.wait_for_timeout(3000)

    # ----------------------------------------------------------------- passos
    def _passo_portal(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Abrindo portal V.top…", step="portal")
        if "appvtop" not in (self.page.url or ""):
            self.page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(1000)

    def _passo_abrir_smartriser(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Clicando no card SmartRiser…", step="smartriser")
        page = self.page
        candidatos = [
            page.get_by_text("SmartRiser - Rede Inteligente Vertical", exact=False),
            page.get_by_text("SmartRiser", exact=False),
            page.locator("div", has_text=re.compile(r"SmartRiser", re.I)),
        ]
        for loc in candidatos:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                continue
        # Fallback: URL direta do SmartRiser
        logger.warning("[VTOP] Card SmartRiser não clicado — navegando pela URL direta.")
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

    def _passo_brownfield(self) -> None:
        assert self.page is not None
        self._set(
            VtopStatus.NAVIGATING,
            "Selecionando Brownfield (risers em HPs até 2024)…",
            step="brownfield",
        )
        page = self.page
        opcao_2024 = page.get_by_text(re.compile(r"Brownfield.*2024|HPs até 2024|HPs ate 2024", re.I))
        if opcao_2024.count() > 0:
            opcao_2024.first.click()
        else:
            page.get_by_text(re.compile(r"Brownfield", re.I)).first.click()
        page.wait_for_timeout(1500)

    def _resolver_obra_id_seguro(self, payload: Dict[str, Any]) -> str:
        """Prioriza obra_id do payload; senão lê BlocoVertical.vtop_obra_id."""
        oid = str(payload.get("obra_id") or "").strip()
        if oid:
            return oid
        cdoi_id = payload.get("cdoi_id")
        nome = str(payload.get("complemento") or payload.get("bloco_nome") or "").strip()
        if not cdoi_id or not nome:
            return ""
        try:
            from tickets.models import BlocoVertical

            blocos = _db_op(lambda: list(BlocoVertical.objects.filter(solicitacao_id=int(cdoi_id))))
            for b in blocos:
                if _bloco_equiv(b.nome_bloco, nome) and (b.vtop_obra_id or "").strip():
                    return str(b.vtop_obra_id).strip()
        except Exception:
            logger.exception("[VTOP] Falha ao resolver obra_id no banco")
        return ""

    def _listar_obras_endereco(self, logradouro: str, numero: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Inventário Brownfield do endereço: complemento → [{id, etapa_txt, joined}, …].

        A tela não tem filtro por endereço: pesquisa MG com período TUDO, exibe todas as
        linhas da DataTable de uma vez e filtra o endereço aqui. Paginação fica de fallback.
        Retorna lista por complemento para detectar duplicatas.
        """
        assert self.page is not None
        page = self.page
        total_grade = self._pesquisar_brownfield_tudo()

        colecionados: Dict[str, Dict[str, Any]] = {}
        linhas_endereco = 0
        parecidos: List[str] = []
        linhas_vistas = 0
        tamanho_pagina = 0
        ids_anterior: List[str] = []
        fim_motivo = ""
        paginas = 0
        for _pagina in range(INVENTARIO_MAX_PAGINAS):
            paginas += 1
            rows = page.evaluate(
                """() => {
                  const nome = (typeof nome_tabela !== 'undefined' && nome_tabela) ? nome_tabela : 'dados_obras';
                  const ths = [...document.querySelectorAll('#' + nome + ' thead th')]
                    .map(th => (th.innerText || '').trim().toUpperCase());
                  const iLog = ths.indexOf('LOGRADOURO'), iNum = ths.indexOf('NUM'), iComp = ths.indexOf('COMP');
                  // Grade trunca textos longos com "..."; o valor completo fica no title
                  const txt = td => td
                    ? (td.getAttribute('title') || td.innerText || '').replace(/\\s+/g, ' ').trim()
                    : '';
                  const out = [];
                  const vistos = new Set();
                  document.querySelectorAll('[onclick*=\"mostrarObra\"]').forEach(el => {
                    const oc = el.getAttribute('onclick') || '';
                    const m = oc.match(/mostrarObra\\(\\s*[\"']?(\\d+)/);
                    if (!m || vistos.has(m[1])) return;
                    const id = m[1];
                    vistos.add(id);
                    const tr = el.closest('tr');
                    const tdsEl = tr ? [...tr.querySelectorAll('td')] : [];
                    const tds = tdsEl.map(td => (td.innerText || '').replace(/\\s+/g, ' ').trim());
                    let etapaTxt = '';
                    for (const td of tds) {
                      if (/^\\d+\\s*-\\s*/.test(td)) { etapaTxt = td; break; }
                    }
                    out.push({
                      id, tds, joined: tds.join(' | '), etapaTxt,
                      logradouro: iLog >= 0 ? txt(tdsEl[iLog]) : '',
                      numero: iNum >= 0 ? txt(tdsEl[iNum]) : '',
                      comp: iComp >= 0 ? txt(tdsEl[iComp]) : '',
                    });
                  });
                  return out;
                }"""
            ) or []
            ids_pagina = [str(r.get("id")) for r in rows]
            for row in rows:
                oid = str(row.get("id") or "").strip()
                if not oid or oid in colecionados:
                    continue
                if not linha_bate_endereco(row, logradouro, numero):
                    grade_log = str(row.get("logradouro") or "")
                    if (
                        grade_log
                        and numero_equivalente(numero, str(row.get("numero") or ""))
                        and logradouro_parecido(logradouro, grade_log)
                        and grade_log not in parecidos
                    ):
                        parecidos.append(grade_log)
                    continue
                row["complemento"] = complemento_da_linha(row)
                colecionados[oid] = row
                linhas_endereco += 1

            if paginas == 1:
                tamanho_pagina = len(ids_pagina)
                if not ids_pagina:
                    fim_motivo = "sem_resultados"
                    break
            elif ids_pagina == ids_anterior:
                # Clicou em "próxima" e a grade não mudou: só é fim se a página for parcial
                fim_motivo = "fim_lista" if len(ids_pagina) < tamanho_pagina else "indeterminado"
                break
            linhas_vistas += len(ids_pagina)
            if paginas > 1 and len(ids_pagina) < tamanho_pagina:
                fim_motivo = "fim_lista"
                break
            ids_anterior = ids_pagina
            if total_grade > 0 and linhas_vistas >= total_grade:
                fim_motivo = "fim_lista"
                break

            # Próxima página
            avancou = page.evaluate(
                """() => {
                  const candidates = [
                    ...document.querySelectorAll('a, button, span'),
                  ];
                  for (const el of candidates) {
                    const t = (el.innerText || el.textContent || '').trim();
                    const title = (el.getAttribute('title') || '').toLowerCase();
                    if (t === '›' || t === '>' || t === '»' || t.toLowerCase() === 'próximo' ||
                        t.toLowerCase() === 'proximo' || title.includes('next')) {
                      const dis = !!el.closest('.disabled') ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        el.hasAttribute('disabled');
                      if (!dis && el.offsetParent !== null) {
                        el.click();
                        return true;
                      }
                    }
                  }
                  // DataTables paginate_button next
                  const n = document.querySelector('.paginate_button.next:not(.disabled)');
                  if (n) { n.click(); return true; }
                  return false;
                }"""
            )
            if not avancou:
                fim_motivo = "fim_lista"
                break
            self._aguardar_troca_pagina(ids_anterior)
        else:
            fim_motivo = "limite"

        if fim_motivo == "fim_lista" and total_grade > 0 and linhas_vistas < total_grade:
            # DataTable diz ter mais linhas do que as lidas no DOM
            fim_motivo = "indeterminado"

        self._inventario_meta = {
            "fim": fim_motivo,
            "paginas": paginas,
            "linhas_vistas": linhas_vistas,
            "linhas_endereco": linhas_endereco,
            "tamanho_pagina": tamanho_pagina,
            "total_grade": total_grade,
            "logradouros_parecidos": parecidos,
        }
        self.state.extras["inventario_meta"] = dict(self._inventario_meta)
        logger.info("[VTOP] Inventário Brownfield: %s", self._inventario_meta)

        # Agrupa por complemento normalizado
        mapa: Dict[str, List[Dict[str, Any]]] = {}
        for oid, row in colecionados.items():
            comp = str(row.get("complemento") or "").strip()
            if not comp:
                continue
            chave = _norm_nome_bloco(comp)
            # Usar chave canônica do primeiro match de alias administrativo
            if chave.startswith("ADMINISTRA"):
                chave = "ADMINISTRACAO"
            item = {
                "id": oid,
                "complemento": comp,
                "etapa_txt": row.get("etapaTxt") or "",
                "joined": row.get("joined") or "",
            }
            mapa.setdefault(chave, []).append(item)

        self.state.extras["obras_endereco"] = {
            k: [x["id"] for x in v] for k, v in mapa.items()
        }
        self.state.extras["obras_endereco_detalhe"] = mapa
        # Persist dump for auditoria produção
        try:
            path = Path(settings.BASE_DIR) / "tmp_vtop_inventario_endereco.json"
            path.write_text(
                json.dumps({"meta": self._inventario_meta, "mapa": mapa}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.state.extras["inventario_path"] = str(path)
        except Exception:
            pass
        return mapa

    def _pesquisar_brownfield_tudo(self) -> int:
        """
        Pesquisa MG com período TUDO (padrão da tela é MÊS ATUAL, que esconde obras de meses
        anteriores) e exibe todas as linhas. Retorna o total da grade, ou -1 se não carregou.
        """
        assert self.page is not None
        page = self.page
        diag: Dict[str, Any] = {}
        pronta = False
        fim_espera = time.time() + BROWNFIELD_PRONTA_S
        while time.time() < fim_espera:
            try:
                diag = page.evaluate(BROWNFIELD_DIAG_JS) or {}
            except Exception as exc:
                # Contexto destruído durante a navegação para fi=2
                diag = {"erro": str(exc)[:120]}
            if brownfield_pronta(diag):
                pronta = True
                break
            page.wait_for_timeout(1000)
        if not pronta:
            self._diagnosticar_brownfield("tela_nao_pronta", diag)
            return -1

        total = -1
        for tentativa in range(1, BROWNFIELD_TENTATIVAS + 1):
            try:
                page.evaluate(BROWNFIELD_PESQUISAR_JS)
            except Exception:
                logger.exception("[VTOP] Falha ao disparar pesquisaObras (tentativa %s)", tentativa)
            for _ in range(BROWNFIELD_TABELA_S):
                page.wait_for_timeout(1000)
                try:
                    total = int(page.evaluate(BROWNFIELD_EXIBIR_TUDO_JS))
                except Exception:
                    total = -1
                if total >= 0:
                    break
            if total >= 0:
                break
            logger.warning(
                "[VTOP] Tabela Brownfield não surgiu em %ss (tentativa %s/%s) — relançando pesquisa",
                BROWNFIELD_TABELA_S, tentativa, BROWNFIELD_TENTATIVAS,
            )
        if total < 0:
            try:
                diag = page.evaluate(BROWNFIELD_DIAG_JS) or {}
            except Exception as exc:
                diag = {"erro": str(exc)[:120]}
            self._diagnosticar_brownfield("tabela_nao_surgiu", diag)
        if total >= 0:
            # DataTable termina a inicialização (idioma) de forma assíncrona: reaplica
            page.wait_for_timeout(1500)
            try:
                total = int(page.evaluate(BROWNFIELD_EXIBIR_TUDO_JS))
            except Exception:
                pass
        logger.info("[VTOP] Pesquisa Brownfield (MG, período TUDO): %s obras na grade", total)
        return total

    def _diagnosticar_brownfield(self, motivo: str, diag: Dict[str, Any]) -> None:
        self._salvar_diagnostico("brownfield", motivo, diag, chave="diagnostico_brownfield")

    def _aguardar_troca_pagina(self, ids_anterior: List[str], timeout_ms: int = 10_000) -> None:
        """Espera a grade trocar de página (ids diferentes) em vez de um sleep fixo."""
        assert self.page is not None
        fim = time.time() + timeout_ms / 1000
        while time.time() < fim:
            self.page.wait_for_timeout(500)
            try:
                ids = self.page.evaluate(
                    """() => {
                      const ids = [];
                      document.querySelectorAll('[onclick*="mostrarObra"]').forEach(el => {
                        const m = (el.getAttribute('onclick') || '').match(/mostrarObra\\(\\s*["']?(\\d+)/);
                        if (m && !ids.includes(m[1])) ids.push(m[1]);
                      });
                      return ids;
                    }"""
                )
            except Exception:
                continue
            if ids and [str(x) for x in ids] != ids_anterior:
                self.page.wait_for_timeout(500)
                return

    def _escolher_obra_da_lista(
        self,
        mapa: Dict[str, List[Dict[str, Any]]],
        complemento: str,
        preferido: str = "",
    ) -> str:
        """Escolhe 1 obra_id para o complemento; se houver duplicata, prefere ID do banco / maior etapa."""
        preferido = (preferido or "").strip()
        candidatos: List[Dict[str, Any]] = []
        for chave, itens in mapa.items():
            if _bloco_equiv(chave, complemento) or _bloco_equiv(
                (itens[0].get("complemento") if itens else ""), complemento
            ):
                candidatos.extend(itens)
        if not candidatos:
            return ""
        if preferido and any(str(c["id"]) == preferido for c in candidatos):
            return preferido

        def _rank(c: Dict[str, Any]) -> Tuple[int, int]:
            et = 0
            m = re.match(r"(\d+)", str(c.get("etapa_txt") or ""))
            if m:
                et = int(m.group(1))
            try:
                oid = int(c["id"])
            except Exception:
                oid = 0
            return (et, oid)

        # Prefere maior etapa; empate → maior id (mais recente)
        melhor = max(candidatos, key=_rank)
        if len(candidatos) > 1:
            ids = [c["id"] for c in candidatos]
            logger.warning(
                "[VTOP] Duplicatas para '%s': %s — usando %s",
                complemento,
                ids,
                melhor["id"],
            )
            self.state.extras.setdefault("duplicatas_detectadas", []).append(
                {"complemento": complemento, "ids": ids, "escolhido": melhor["id"]}
            )
        return str(melhor["id"])

    def _passo_tentar_reusar_obra_lista(self, payload: Dict[str, Any]) -> None:
        """
        Antes de criar: se o complemento já existir no endereço, reusa o ID
        (evita duplicar obra no mesmo endereço).
        """
        complemento = str(payload.get("complemento") or payload.get("bloco_nome") or "")
        logradouro = str(payload.get("logradouro") or "")
        numero = str(payload.get("numero") or "")
        self._set(
            VtopStatus.NAVIGATING,
            f"Inventário Brownfield: '{complemento}' em {logradouro} {numero}…",
            step="localizar",
        )
        mapa = self._listar_obras_endereco(logradouro, numero)
        preferido = str(payload.get("obra_id") or "").strip()
        encontrado = self._escolher_obra_da_lista(mapa, complemento, preferido=preferido)
        if encontrado:
            payload["obra_id"] = encontrado
            self._payload_atual = dict(payload)
            self.state.extras["obra_id"] = encontrado
            self.state.extras["reusada_da_lista"] = True
            _db_op(persistir_vtop_obra_bloco, payload.get("cdoi_id"), complemento, encontrado)
            self._set(
                VtopStatus.NAVIGATING,
                f"Complemento '{complemento}' já existe (id={encontrado}) — reutilizando, não cria duplicata.",
                step="localizar",
            )
            self._passo_abrir_obra_existente(encontrado)
        else:
            # Não achou o mesmo complemento → caminho criar obra nova
            total = sum(len(v) for v in mapa.values())
            bloqueio = motivo_bloqueio_inventario(self._inventario_meta, total)
            if bloqueio:
                raise RuntimeError(bloqueio)
            # Descarta obra_id preferido do banco: lista é a fonte da verdade
            payload.pop("obra_id", None)
            self._payload_atual = dict(payload)
            self.state.extras["reusada_da_lista"] = False
            self.state.extras.pop("obra_id", None)
            if not vtop_criar_permitido(payload):
                raise RuntimeError(
                    f"Complemento '{complemento}' não existe na lista, mas criação "
                    "está bloqueada (VTOP_BLOQUEAR_CRIAR_OBRA / VTOP_PERMITIR_CRIAR_OBRA)."
                )
            self._set(
                VtopStatus.NAVIGATING,
                f"Complemento '{complemento}' ausente na grade ({total} obras no endereço) — criando obra nova.",
                step="localizar",
            )

    def _passo_concluir_cadastro_se_preciso(self, payload: Dict[str, Any]) -> None:
        """
        Fluxo idempotente de produção:
          - se etapa >= 2: só sincroniza banco e encerra
          - senão: preenche → salva (se botão visível) → valida → relê etapa
        Falha de anexo não aborta (salvo VTOP_ANEXO_OBRIGATORIO).
        """
        assert self.page is not None
        etapa = ler_etapa_obra_page(self.page)
        obra_id = str(
            self.state.extras.get("obra_id")
            or payload.get("obra_id")
            or self._detectar_obra_id()
            or ""
        )
        if not obra_id:
            raise RuntimeError(
                "Cadastro sem obra_id — obra não confirmada na V.tal; nada foi preenchido/validado."
            )
        self.state.extras["obra_id"] = obra_id
        self.state.extras["obra_etapa_antes"] = etapa
        if etapa is not None and etapa >= 2:
            if obra_id:
                self._gravar_vinculo_obra(obra_id, etapa=etapa)
            self._set(
                VtopStatus.DONE,
                f"Obra {obra_id} já na etapa {etapa} — nada a criar/validar.",
                step="concluir_cadastro",
            )
            return

        try:
            self._passo_cadastro(payload)
        except Exception as exc:
            if getattr(settings, "VTOP_ANEXO_OBRIGATORIO", False):
                raise
            logger.exception("[VTOP] Cadastro com falha parcial (segue salvar/validar): %s", exc)
            self.state.extras["cadastro_parcial_erro"] = str(exc)

        btn_salvar = self.page.locator("#btn_salvarEtapa")
        if btn_salvar.count() and btn_salvar.first.is_visible():
            self._passo_salvar_disquete()
        else:
            logger.warning("[VTOP] #btn_salvarEtapa invisível — pulando salvar.")

        btn_val = self.page.locator("#btn_validarEtapa")
        if btn_val.count() and btn_val.first.is_visible():
            self._passo_validar()
        else:
            logger.warning("[VTOP] #btn_validarEtapa invisível — pulando validar.")

        self.page.wait_for_timeout(1500)
        etapa_depois = ler_etapa_obra_page(self.page)
        self.state.extras["obra_etapa_apos_validar"] = etapa_depois
        if obra_id and etapa_depois is not None:
            self._gravar_vinculo_obra(obra_id, etapa=etapa_depois)
        self._set(
            VtopStatus.VALIDATING,
            f"Cadastro concluído obra={obra_id} etapa={etapa_depois}.",
            step="concluir_cadastro",
        )

    def _passo_abrir_modal_obra_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self.state.extras["criando_obra"] = True
        self._passo_abrir_modal_obra()

    def _passo_preencher_obra_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self._passo_preencher_obra(payload, salvar=False)

    def _passo_coords_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        # Obra nova: o "Salvar" do mapa só preenche #input_lat/#input_lon do modal e fecha
        # #popup_map (nada vai ao servidor). Sem ele, criarObra() envia 0,0 e o popup
        # aberto intercepta o clique em #b_criar_obra.
        self._passo_coordenadas(payload, salvar=True)

    def _passo_salvar_obra_modal_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        if not vtop_criar_permitido(payload):
            raise RuntimeError(
                "Criação bloqueada por configuração "
                "(VTOP_BLOQUEAR_CRIAR_OBRA / VTOP_PERMITIR_CRIAR_OBRA)."
            )
        self.state.extras["criando_obra"] = True
        self._passo_salvar_obra_modal()

    def _passo_coords_pos_salvar_se_preciso(self, payload: Dict[str, Any]) -> None:
        if self.state.extras.get("reusada_da_lista"):
            return
        self._exigir_obra_aberta("coordenadas pós-salvar")
        self._passo_coords_pos_salvar(payload)

    def _exigir_obra_aberta(self, etapa: str) -> str:
        """Sem obra_id + obra.jsp aberta, mapa/cadastro atuariam na grade ou em outra obra."""
        assert self.page is not None
        obra_id = str(self.state.extras.get("obra_id") or "").strip()
        if not obra_id or "obra.jsp" not in (self.page.url or ""):
            raise RuntimeError(
                f"{etapa.capitalize()} sem obra aberta (obra_id={obra_id or '?'}, URL={self.page.url}) — "
                "confira na V.tal antes de tentar de novo."
            )
        return obra_id

    def _passo_abrir_modal_obra(self) -> None:
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, "Abrindo formulário (+)…", step="obra_modal")
        page = self.page
        candidatos = [
            page.locator("#addUmaObra"),
            page.get_by_title("Adicionar obra manualmente"),
            page.locator("button:has(i.fa-square-plus)"),
            page.locator("i.fa-square-plus.icone_obra"),
        ]
        clicado = False
        for loc in candidatos:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    clicado = True
                    break
            except Exception:
                continue
        if not clicado:
            raise RuntimeError(
                "Não encontrei o botão #addUmaObra (Adicionar obra manualmente)."
            )
        page.get_by_text("Cadastro de nova obra").wait_for(state="visible", timeout=15_000)

    def _preencher_por_label(self, label: str, valor: str) -> bool:
        """Tenta preencher input/select associado ao label. Retorna True se conseguiu."""
        assert self.page is not None
        if valor is None or str(valor) == "":
            return False
        page = self.page
        # 1) get_by_label
        try:
            campo = page.get_by_label(re.compile(re.escape(label), re.I), exact=False)
            if campo.count() > 0:
                tag = campo.first.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    campo.first.select_option(label=str(valor))
                else:
                    campo.first.fill(str(valor))
                return True
        except Exception:
            pass
        # 2) texto do label → input irmão / seguinte
        try:
            lab = page.locator(f"label:has-text('{label}')").first
            if lab.count() > 0:
                for sel in ["xpath=following::input[1]", "xpath=following::select[1]", "xpath=../input", "xpath=../select"]:
                    alvo = lab.locator(sel)
                    if alvo.count() > 0:
                        tag = alvo.first.evaluate("el => el.tagName.toLowerCase()")
                        if tag == "select":
                            try:
                                alvo.first.select_option(value=str(valor))
                            except Exception:
                                alvo.first.select_option(label=str(valor))
                        else:
                            alvo.first.fill(str(valor))
                        return True
        except Exception:
            pass
        logger.warning("[VTOP] Campo não mapeado ainda: %s", label)
        return False

    def _fill_id(self, element_id: str, valor: str) -> bool:
        assert self.page is not None
        if valor is None or str(valor) == "":
            return False
        loc = self.page.locator(f"#{element_id}")
        if loc.count() == 0:
            logger.warning("[VTOP] #%s não encontrado", element_id)
            return False
        tag = loc.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            try:
                loc.first.select_option(value=str(valor))
            except Exception:
                loc.first.select_option(label=str(valor))
            return True

        # Alguns campos do modal nascem disabled até escolher UF / tipo
        disabled = False
        try:
            disabled = bool(loc.first.is_disabled())
        except Exception:
            pass
        if disabled:
            loc.first.evaluate(
                """(el, v) => {
                    el.removeAttribute('disabled');
                    el.value = v;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                str(valor),
            )
            return True

        loc.first.fill(str(valor))
        return True

    def _passo_preencher_obra(self, payload: Dict[str, Any], *, salvar: bool = False) -> None:
        """
        Preenche o modal 'Cadastro de nova obra' pelos IDs mapeados no DOM.

        Uma obra = um bloco (complemento = nome do bloco; UMS = HPs do bloco).
        """
        self._set(VtopStatus.FILLING_OBRA, "Preenchendo Cadastro de nova obra…", step="preencher_obra")
        assert self.page is not None

        complemento = (payload.get("complemento") or payload.get("bloco_nome") or "").strip()
        ums = str(payload.get("total_hps", "") or "")
        self.state.extras["obra_bloco"] = complemento
        self.state.extras["obra_ums"] = ums

        # UF primeiro — libera/condiciona LOCALIDADE e demais
        mapa = [
            ("sel_uf_obra", payload.get("uf", "")),
            ("input_cod_survey", payload.get("cod_survey", "")),
            ("input_localidade_abrev", payload.get("cidade", "")),
            ("input_estacao_abastecedora", payload.get("estacao", "")),
            ("input_logradouro", payload.get("logradouro", "")),
            ("input_num_fachada", payload.get("numero", "")),
            ("input_bairro", payload.get("bairro", "")),
            ("input_complemento", complemento),
            ("input_celula", payload.get("celula", "")),
            ("input_nome_cdo", payload.get("cdoi_codigo", "")),
            ("input_quantidade_ums", ums),
        ]
        ok: List[str] = []
        for eid, valor in mapa:
            if eid == "sel_uf_obra" and valor:
                if self._fill_id(eid, str(valor)):
                    ok.append(eid)
                    self.page.wait_for_timeout(800)
                continue
            if self._fill_id(eid, str(valor) if valor is not None else ""):
                ok.append(eid)
        self.state.extras["obra_campos_ok"] = ok
        self._set(
            VtopStatus.FILLING_OBRA,
            f"Obra '{complemento}' UMS={ums} ({len(ok)} campos). Salvar={'sim' if salvar else 'não'}.",
            step="preencher_obra",
        )
        if salvar:
            self._passo_salvar_obra_modal()

    def _passo_salvar_obra_modal(self) -> None:
        """
        Cria a obra (#b_criar_obra). No success o JS chama mostrarObra()
        e abre obra.jsp em nova aba (target=_blank).
        """
        assert self.page is not None
        assert self.context is not None
        self._set(VtopStatus.SAVING, "Clicando Salvar no modal da obra (#b_criar_obra)…", step="salvar_obra")
        page = self.page
        pagina_grade = page

        campos = self._campos_vazios_obra()
        self.state.extras["obra_campos_vazios"] = campos
        if campos.get("obrigatorios"):
            logger.warning("[VTOP] Campos obrigatórios vazios no modal da obra: %s", campos["obrigatorios"])
        self._preparar_modal_para_criar_obra()

        mensagens: List[str] = []
        novas_abas: List[Any] = []
        respostas_criar: List[Any] = []

        def _resposta(resp) -> None:
            if "CriarObra" in (resp.url or ""):
                respostas_criar.append(resp)

        def _aceitar(dialog) -> None:
            mensagens.append(dialog.message)
            logger.info("[VTOP] Dialog ao salvar obra: %s", dialog.message)
            try:
                dialog.accept()
            except Exception:
                pass

        def _nova_aba(aba) -> None:
            novas_abas.append(aba)

        page.on("dialog", _aceitar)
        page.on("response", _resposta)
        self.context.on("page", _nova_aba)
        try:
            btn = page.locator("#b_criar_obra")
            # Clique ÚNICO: um segundo clique pode criar obra duplicada na V.tal
            if btn.count() == 0:
                page.get_by_role("button", name=re.compile(r"Salvar", re.I)).first.click()
            else:
                btn.first.click()
            resultado, destino = self._aguardar_resultado_salvar_obra(page, novas_abas, mensagens)
        finally:
            page.remove_listener("dialog", _aceitar)
            page.remove_listener("response", _resposta)
            self.context.remove_listener("page", _nova_aba)

        # criarObra(): success(id_obra) → mostrarObra(id) faz POST em obra.jsp (URL sem ?id=)
        id_resposta = ""
        for resp in respostas_criar:
            try:
                corpo = (resp.text() or "").strip()
            except Exception:
                corpo = ""
            self.state.extras["criar_obra_resposta"] = {"status": resp.status, "corpo": corpo[:200]}
            if resp.ok and corpo.isdigit():
                id_resposta = corpo

        self.state.extras["salvar_obra_resultado"] = resultado
        self.state.extras["salvar_obra_mensagens"] = mensagens[:10]
        logger.info(
            "[VTOP] Resultado do Salvar obra: %s id_resposta=%s mensagens=%s",
            resultado, id_resposta or "-", mensagens[:5],
        )

        obra_id = id_resposta
        if destino is not None:
            self.page = destino
            page = destino
            logger.info("[VTOP] Obra aberta (%s): %s", resultado, page.url)
            obra_id = obra_id or self._detectar_obra_id()

        if not obra_id:
            self._salvar_diagnostico(
                "salvar_obra",
                resultado,
                {"url": page.url, "mensagens": mensagens[:10], "campos": campos},
                chave="diagnostico_salvar_obra",
            )
            if destino is not None and destino is not pagina_grade:
                self.page = pagina_grade
            obra_id = self._confirmar_obra_pelo_inventario()
            page = self.page
        else:
            self.state.extras["obra_id"] = obra_id
            self._gravar_vinculo_obra(obra_id)

        try:
            page.locator("#btn_salvarEtapa").wait_for(state="visible", timeout=45_000)
        except Exception:
            try:
                page.get_by_text(re.compile(r"NOME DO CONDOM", re.I)).first.wait_for(
                    state="visible", timeout=15_000
                )
            except Exception:
                logger.warning("[VTOP] Tela de cadastro pós-salvar não detectada. URL=%s", page.url)

        page.wait_for_timeout(1000)
        self.state.extras["url_apos_salvar_obra"] = page.url
        self._set(
            VtopStatus.SAVING,
            f"Obra salva (id={obra_id or '?'}). URL={page.url}",
            step="salvar_obra",
        )

    def _preparar_modal_para_criar_obra(self) -> None:
        """Fecha #popup_map (intercepta o clique em Salvar) e exige coords no modal."""
        assert self.page is not None
        page = self.page
        try:
            if page.evaluate("() => { const p = document.getElementById('popup_map'); return !!(p && p.offsetParent !== null); }"):
                logger.warning("[VTOP] #popup_map ainda aberto antes de salvar a obra — fechando")
                page.evaluate("() => { if (typeof fechaPopupMap === 'function') fechaPopupMap(); }")
                page.locator("#popup_map").wait_for(state="hidden", timeout=5_000)
        except Exception:
            logger.exception("[VTOP] Falha ao fechar #popup_map")
        payload = self._payload_atual or {}
        if (payload.get("latitude") or "").strip() and (payload.get("longitude") or "").strip():
            try:
                lat = float(page.locator("#input_lat").input_value() or 0)
                lon = float(page.locator("#input_lon").input_value() or 0)
            except Exception:
                lat = lon = 0.0
            if not lat or not lon:
                raise RuntimeError(
                    "Coordenadas não aplicadas no formulário da obra (lat/lon = 0) — obra NÃO foi salva."
                )

    def _aguardar_resultado_salvar_obra(
        self, page, novas_abas: List[Any], mensagens: List[str]
    ) -> Tuple[str, Any]:
        """
        Após o clique em Salvar: ('nova_aba'|'mesma_aba', página da obra) ou
        ('modal_fechado'|'mensagem'|'timeout', None). Não clica em nada.
        """
        fim = time.time() + SALVAR_OBRA_TIMEOUT_S
        sinal_em: Optional[float] = None
        sinal = ""
        while time.time() < fim:
            if novas_abas:
                aba = novas_abas[0]
                try:
                    aba.wait_for_load_state("domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                return "nova_aba", aba
            try:
                if "obra.jsp" in (page.url or ""):
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                    return "mesma_aba", page
            except Exception:
                pass
            if not sinal:
                try:
                    txt = page.evaluate(SALVAR_OBRA_MENSAGENS_JS) or ""
                except Exception:
                    txt = ""
                if txt and txt not in mensagens:
                    mensagens.append(txt)
                try:
                    modal_aberto = bool(page.evaluate(SALVAR_OBRA_MODAL_ABERTO_JS))
                except Exception:
                    modal_aberto = True
                if not modal_aberto:
                    sinal = "modal_fechado"
                elif mensagens:
                    sinal = "mensagem"
                if sinal:
                    sinal_em = time.time()
            # Sucesso costuma abrir obra.jsp logo depois de fechar o modal / avisar
            if sinal and sinal_em and time.time() - sinal_em > SALVAR_OBRA_APOS_SINAL_S:
                return sinal, None
            try:
                page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
        return sinal or "timeout", None

    def _campos_vazios_obra(self) -> Dict[str, List[str]]:
        """Campos visíveis vazios do modal 'Cadastro de nova obra' (obrigatórios à parte)."""
        assert self.page is not None
        try:
            return self.page.evaluate(OBRA_CAMPOS_VAZIOS_JS) or {}
        except Exception:
            return {}

    def _salvar_diagnostico(self, prefixo: str, motivo: str, diag: Dict[str, Any], *, chave: str) -> None:
        """Registra o contexto e salva screenshot+HTML fora do repositório."""
        assert self.page is not None
        base = os.path.join(
            tempfile.gettempdir(),
            f"vtop_{prefixo}_{motivo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        arquivos: List[str] = []
        try:
            self.page.screenshot(path=base + ".png", full_page=True)
            arquivos.append(base + ".png")
        except Exception:
            logger.exception("[VTOP] Falha no screenshot de diagnóstico (%s)", prefixo)
        try:
            with open(base + ".html", "w", encoding="utf-8") as fh:
                fh.write(self.page.content())
            arquivos.append(base + ".html")
        except Exception:
            logger.exception("[VTOP] Falha ao salvar HTML de diagnóstico (%s)", prefixo)
        logger.warning("[VTOP] Diagnóstico %s/%s: diag=%s arquivos=%s", prefixo, motivo, diag, arquivos)
        self.state.extras[chave] = {"motivo": motivo, "diag": diag, "arquivos": arquivos}

    def _confirmar_obra_pelo_inventario(self) -> str:
        """
        Obra não abriu após Salvar: procura o complemento recém-criado na grade.
        Exatamente 1 → abre e vincula; 2+ → possível duplicata; 0 → não confirmada.
        """
        payload = self._payload_atual or {}
        complemento = str(payload.get("complemento") or payload.get("bloco_nome") or "").strip()
        self._set(
            VtopStatus.SAVING,
            f"Obra não abriu após salvar — conferindo '{complemento}' no inventário…",
            step="salvar_obra",
        )
        mapa = self._listar_obras_endereco(
            str(payload.get("logradouro") or ""), str(payload.get("numero") or "")
        )
        ids = obras_do_complemento(mapa, complemento)
        self.state.extras["obras_pos_salvar"] = ids
        if len(ids) > 1:
            raise RuntimeError(
                f"Possível duplicata: {len(ids)} obras '{complemento}' no endereço após salvar "
                f"(ids {', '.join(ids)}) — confira na V.tal antes de tentar de novo."
            )
        if not ids:
            raise RuntimeError("Obra não confirmada após salvar — confira na V.tal antes de tentar de novo.")
        self._passo_abrir_obra_existente(ids[0])
        return ids[0]

    def _gravar_vinculo_obra(self, obra_id: str, etapa: Optional[int] = None) -> None:
        """Persiste obra_id/etapa no BlocoVertical do payload atual."""
        payload = self._payload_atual or {}
        nome = (
            payload.get("complemento")
            or payload.get("bloco_nome")
            or self.state.extras.get("obra_bloco")
            or ""
        )
        _db_op(
            persistir_vtop_obra_bloco,
            payload.get("cdoi_id"),
            str(nome),
            str(obra_id),
            etapa=etapa,
        )

    def _detectar_obra_id(self) -> str:
        assert self.page is not None
        page = self.page
        for sel in ("input[name='id']", "input#id", "input[name='id_obra']"):
            loc = page.locator(sel)
            if loc.count() > 0:
                val = (loc.first.input_value() or "").strip()
                if val.isdigit():
                    return val
        m = re.search(r"edit_(\d+)_\d+_", page.content()[:200_000])
        if m:
            return m.group(1)
        m = re.search(r"[?&]id=(\d+)", page.url)
        if m:
            return m.group(1)
        return ""

    def _passo_abrir_obra_existente(self, obra_id: str) -> None:
        """Abre obra.jsp?id=… (GET funciona no SmartRiser atual)."""
        assert self.page is not None
        self._set(VtopStatus.NAVIGATING, f"Abrindo obra existente {obra_id}…", step="abrir_obra")
        url = f"{VTOP_SMARTRISER_URL}obra.jsp?id={obra_id}"
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.locator("#btn_salvarEtapa").wait_for(state="attached", timeout=60_000)
        # pesquisaCheckList preenche .item_checklist via AJAX
        self.page.locator(".item_checklist").first.wait_for(state="visible", timeout=60_000)
        self.page.wait_for_timeout(800)
        self.state.extras["obra_id"] = str(obra_id)
        self.state.extras["url_obra"] = self.page.url
        self._gravar_vinculo_obra(str(obra_id))
        self._set(VtopStatus.NAVIGATING, f"Obra {obra_id} aberta.", step="abrir_obra")

    def _passo_coords_pos_salvar(self, payload: Dict[str, Any]) -> None:
        """Só reabre mapa após salvar obra se as coords não foram gravadas no modal."""
        if payload.get("salvar_coords") or self.state.extras.get("coords_preenchidas"):
            self._set(
                VtopStatus.FILLING_COORDS,
                "Coords já gravadas no modal — pulando coords pós-salvar.",
                step="coords_pos_salvar",
            )
            return
        self._passo_coordenadas(payload, salvar=True)

    def _abrir_modal_coordenadas(self) -> bool:
        """Abre o mapa clicando em img/icon_map.png (onclick=abrirMapa...)."""
        assert self.page is not None
        page = self.page
        # Já aberto?
        if page.locator("text=Latitude").count() > 0 or page.get_by_text(re.compile(r"^Latitude", re.I)).count() > 0:
            try:
                if page.get_by_text(re.compile(r"Latitude\s*:", re.I)).first.is_visible():
                    return True
            except Exception:
                pass

        # Seletor real mapeado no DevTools (ago/2026):
        # <th id="lat_long">...<a onclick="abrirMapa(-1,0,0,0,0)"><img src="img/icon_map.png"></a>
        candidatos = [
            page.locator('#lat_long a[onclick*="abrirMapa"]'),
            page.locator('#lat_long img[src*="icon_map.png"]'),
            page.locator('a[onclick*="abrirMapa"] img[src*="icon_map.png"]'),
            page.locator('img[src="img/icon_map.png"]'),
            page.locator('img[src*="icon_map.png"]'),
            page.locator('a[onclick*="abrirMapa"]'),
        ]
        for loc in candidatos:
            try:
                if loc.count() == 0:
                    continue
                alvo = loc.first
                if not alvo.is_visible():
                    continue
                alvo.click()
                page.wait_for_timeout(1200)
                if page.get_by_text(re.compile(r"Latitude", re.I)).count() > 0:
                    return True
            except Exception:
                continue

        # Fallback: chamar a função JS diretamente no contexto da página
        try:
            page.evaluate("() => { if (typeof abrirMapa === 'function') abrirMapa(-1,0,0,0,0); }")
            page.wait_for_timeout(1200)
            if page.get_by_text(re.compile(r"Latitude", re.I)).count() > 0:
                return True
        except Exception:
            pass
        return False

    def _preencher_inputs_coordenadas(self, lat: str, lng: str) -> bool:
        """Preenche #edit_lat e #edit_lon no modal do mapa."""
        assert self.page is not None
        page = self.page
        ok = False

        # IDs reais mapeados no DevTools (ago/2026)
        if page.locator("#edit_lat").count() > 0:
            page.locator("#edit_lat").fill(lat)
            ok = True
        if page.locator("#edit_lon").count() > 0:
            page.locator("#edit_lon").fill(lng)
            ok = True
        if ok:
            return True

        # Fallbacks
        for label, valor in (("Latitude", lat), ("Longitude", lng)):
            if self._preencher_por_label(label, valor):
                ok = True
        return ok

    def _passo_coordenadas(self, payload: Dict[str, Any], *, salvar: bool = False) -> None:
        lat = (payload.get("latitude") or "").strip()
        lng = (payload.get("longitude") or "").strip()
        if not lat or not lng:
            self._set(
                VtopStatus.FILLING_COORDS,
                "Lat/Long ausentes no payload — pulando coordenadas.",
                step="coords",
            )
            return

        assert self.page is not None
        self._set(
            VtopStatus.FILLING_COORDS,
            "Clicando icon_map.png e preenchendo lat/long…",
            step="coords",
        )
        aberto = self._abrir_modal_coordenadas()
        if not aberto:
            self._set(
                VtopStatus.FILLING_COORDS,
                "Não abriu o modal do mapa (icon_map.png / abrirMapa).",
                step="coords",
            )
            self.state.extras["coords_abertas"] = False
            return

        self.state.extras["coords_abertas"] = True
        page = self.page
        page.locator("#edit_lat").wait_for(state="visible", timeout=10_000)
        page.locator("#edit_lon").wait_for(state="visible", timeout=10_000)
        page.locator("#edit_lat").fill("")
        page.locator("#edit_lon").fill("")
        page.locator("#edit_lat").fill(lat)
        page.locator("#edit_lon").fill(lng)
        vlat = page.locator("#edit_lat").input_value()
        vlon = page.locator("#edit_lon").input_value()
        self.state.extras["coords_valores"] = {"lat": vlat, "lon": vlon}
        logger.info("[VTOP] Coords nos inputs: lat=%s lon=%s", vlat, vlon)

        # Procurar = setCoordenada() (ajax + reposiciona infoWindow)
        try:
            with page.expect_response(lambda r: "validalatlon" in (r.url or ""), timeout=15_000):
                page.locator("#b_map_procurar").click()
        except Exception:
            page.locator("#b_map_procurar").click()
        page.wait_for_timeout(2000)

        if not salvar:
            self.state.extras["coords_preenchidas"] = True
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Coords preenchidas ({lat}, {lng}) + Procurar — NÃO salvou o mapa.",
                step="coords",
            )
            return

        # Playwright descarta dialogs por padrão; preferir handler do context do script.
        def _aceitar_confirm(dialog) -> None:
            try:
                logger.info("[VTOP] Confirm mapa: %s", dialog.message)
                dialog.accept()
            except Exception as exc:
                logger.warning("[VTOP] Dialog mapa já tratado: %s", exc)

        if not getattr(self, "_dialog_via_context", False):
            page.once("dialog", _aceitar_confirm)
        page.locator("#b_salvar_coord").click()
        page.wait_for_timeout(1500)

        depois = page.evaluate(
            """() => ({
              span_lat: (document.querySelector('#span_lat')||{}).innerText || '',
              span_lon: (document.querySelector('#span_lon')||{}).innerText || '',
              input_lat: (document.querySelector('#input_lat')||{}).value || '',
              input_lon: (document.querySelector('#input_lon')||{}).value || '',
            })"""
        )
        self.state.extras["coords_apos_salvar"] = depois
        gravou = lat[:8] in str(depois.get("span_lat") or "") or lat[:8] in str(
            depois.get("input_lat") or ""
        )
        self.state.extras["coords_preenchidas"] = gravou

        if gravou:
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Coords salvas: {depois.get('span_lat')},{depois.get('span_lon')}",
                step="coords",
            )
            return

        # Bypass do confirm: grava direto nos campos (mesma lógica do OK do confirm)
        logger.warning("[VTOP] Confirm/salvar não gravou (%s) — gravando direto nos spans", depois)
        page.evaluate(
            """([lat, lon]) => {
              const latN = parseFloat(lat);
              const lonN = parseFloat(lon);
              const spanLat = document.querySelector('#span_lat');
              const spanLon = document.querySelector('#span_lon');
              const inputLat = document.querySelector('#input_lat');
              const inputLon = document.querySelector('#input_lon');
              if (spanLat) spanLat.innerHTML = latN.toFixed(7);
              if (spanLon) spanLon.innerHTML = lonN.toFixed(7);
              if (inputLat) inputLat.value = String(latN);
              if (inputLon) inputLon.value = String(lonN);
              const popup = document.querySelector('#popup_map');
              if (popup && window.jQuery) { window.jQuery(popup).fadeOut('fast'); }
              else if (popup) { popup.style.display = 'none'; }
            }""",
            [lat, lng],
        )
        page.wait_for_timeout(800)
        depois2 = page.evaluate(
            """() => ({
              span_lat: (document.querySelector('#span_lat')||{}).innerText || '',
              span_lon: (document.querySelector('#span_lon')||{}).innerText || '',
              input_lat: (document.querySelector('#input_lat')||{}).value || '',
              input_lon: (document.querySelector('#input_lon')||{}).value || '',
            })"""
        )
        self.state.extras["coords_apos_fallback"] = depois2
        gravou2 = lat[:8] in str(depois2.get("span_lat") or "") or lat[:8] in str(
            depois2.get("input_lat") or ""
        )
        self.state.extras["coords_preenchidas"] = gravou2
        if gravou2:
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Coords gravadas (fallback): {depois2.get('span_lat')},{depois2.get('span_lon')}",
                step="coords",
            )
        else:
            self._set(
                VtopStatus.FILLING_COORDS,
                f"Falha ao gravar coords ({depois2}).",
                step="coords",
                error="coords_not_saved",
            )

    def _dump_campos_visiveis(self, outfile: str) -> List[Dict[str, Any]]:
        assert self.page is not None
        data = self.page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll('input, select, textarea, button, a, img'));
              return nodes.map(el => {
                const r = el.getBoundingClientRect();
                const cs = getComputedStyle(el);
                const visible = !!(r.width && r.height && cs.visibility !== 'hidden' && cs.display !== 'none');
                if (!visible && el.type !== 'file' && el.type !== 'hidden') return null;
                let label = '';
                if (el.id) {
                  const l = document.querySelector(`label[for="${el.id}"]`);
                  if (l) label = (l.innerText || '').trim();
                }
                if (!label) {
                  const row = el.closest('tr, .form-group, div');
                  if (row) label = (row.innerText || '').trim().split('\\n')[0].slice(0, 120);
                }
                return {
                  tag: el.tagName,
                  type: el.type || '',
                  id: el.id || '',
                  name: el.name || '',
                  value: (el.value || '').toString().slice(0, 80),
                  placeholder: el.placeholder || '',
                  title: el.title || '',
                  alt: el.alt || '',
                  src: (el.getAttribute('src') || '').slice(0, 120),
                  onclick: (el.getAttribute('onclick') || '').slice(0, 120),
                  label,
                  visible,
                  disabled: !!el.disabled,
                  options: el.tagName === 'SELECT'
                    ? Array.from(el.options).slice(0, 30).map(o => ({v: o.value, t: o.text}))
                    : undefined,
                };
              }).filter(Boolean);
            }"""
        )
        path = Path(settings.BASE_DIR) / outfile
        path.write_text(
            json.dumps({"url": self.page.url, "fields": data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[VTOP] Dump de campos: %s (%s itens)", path, len(data))
        self.state.extras["dom_dump"] = str(path)
        return data

    def _dump_checklist_cadastro(self, outfile: str = "tmp_vtop_dom_cadastro_obra.json") -> Dict[str, Any]:
        """Dump estruturado dos itens do checklist (rótulo + inputs)."""
        assert self.page is not None
        data = self.page.evaluate(
            """() => {
              const out = {url: location.href, header: {}, itens: []};
              ['cod_survey','uf','localidade_abrev','estacao_abastecedora','meta',
               'logradouro','num_fachada','bairro','complemento','celula','nome_cdo',
               'quantidade_ums'].forEach(id => {
                const el = document.getElementById(id);
                if (el) out.header[id] = (el.innerText || el.textContent || '').trim();
              });
              document.querySelectorAll('.item_checklist').forEach((div, idx) => {
                const labelEl = div.querySelector('table td');
                const label = labelEl ? (labelEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                const inputs = Array.from(div.querySelectorAll('input,select,textarea')).map(el => ({
                  id: el.id || '', type: el.type || el.tagName, value: (el.value || '').toString().slice(0, 120),
                  options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.value) : undefined,
                }));
                out.itens.push({idx, label, inputs});
              });
              return out;
            }"""
        )
        path = Path(settings.BASE_DIR) / outfile
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.state.extras["dom_dump"] = str(path)
        return data

    def _passo_cadastro(self, payload: Dict[str, Any]) -> None:
        assert self.page is not None
        self._set(VtopStatus.FILLING_CADASTRO, "Preenchendo aba Cadastro…", step="cadastro")
        page = self.page
        page.locator("#btn_salvarEtapa").wait_for(state="attached", timeout=45_000)
        page.locator(".item_checklist").first.wait_for(state="visible", timeout=45_000)
        page.wait_for_timeout(500)

        dump = self._dump_checklist_cadastro("tmp_vtop_dom_cadastro_obra.json")
        obra_id = self._detectar_obra_id() or str(payload.get("obra_id") or "")
        self.state.extras["obra_id"] = obra_id

        bloco = payload.get("bloco_nome") or payload.get("complemento") or ""
        andares = int(payload.get("andares") or 0)
        aptos = int(payload.get("aptos") or 0)
        ums = int(payload.get("total_hps") or 0)
        # Se a obra já existe, prioriza QUANTIDADE UMS do header (pode diferir do CDOI)
        try:
            ums_header = (page.locator("#quantidade_ums").inner_text(timeout=2000) or "").strip()
            if ums_header.isdigit() and int(ums_header) > 0:
                ums = int(ums_header)
                self.state.extras["ums_obra"] = ums
        except Exception:
            pass
        prev_bloco = calcular_pre_venda_bloco(ums)
        if payload.get("pre_venda_forcada") is not None:
            prev_bloco = int(payload["pre_venda_forcada"])
        caract = (payload.get("caracteristicas") or "").strip() or (
            f"{bloco}: {andares} andares, {aptos} ums/andar ({ums} HPs)"
        )
        # Recalcula texto se UMS da obra diferir do payload
        if ums and str(ums) not in caract:
            caract = f"{bloco}: {andares} andares × {aptos} ums/andar ({ums} HPs)" if andares and aptos else (
                f"{bloco}: {ums} HPs"
            )

        id_valores: Dict[str, str] = {}
        if obra_id:
            id_valores[f"edit_{obra_id}_1_2"] = str(payload.get("nome_condominio") or "")
            id_valores[f"edit_{obra_id}_1_3"] = str(payload.get("nome_sindico") or "")
            id_valores[f"edit_{obra_id}_1_4"] = str(payload.get("contato") or "")
            id_valores[f"edit_{obra_id}_1_6"] = str(payload.get("codigo_sap") or "")
            id_valores[f"edit_{obra_id}_1_8"] = caract

        id_valores["input_blocos"] = "1"
        id_valores["input_andares"] = str(andares)
        id_valores["input_total_hps"] = str(ums)
        id_valores["input_prevenda"] = str(prev_bloco)

        for item in dump.get("itens") or []:
            label_u = (item.get("label") or "").upper()
            inputs = item.get("inputs") or []
            edit_ids = [i["id"] for i in inputs if str(i.get("id", "")).startswith("edit_")]
            if not edit_ids:
                continue
            eid = edit_ids[0]
            # CARTA / FOTOS ficam vazios aqui (anexo via fa-square-plus → addDocFoto)
            if "CARTA" in label_u or "AUTORIZA" in label_u or "FOTO" in label_u or "FAIXADA" in label_u or "FACHADA" in label_u:
                continue
            if "NOME DO CONDOM" in label_u and "SIND" not in label_u:
                id_valores[eid] = str(payload.get("nome_condominio") or "")
            elif ("NOME DO SINDICO" in label_u or "NOME DO SÍNDICO" in label_u) and "CONTATO" not in label_u:
                id_valores[eid] = str(payload.get("nome_sindico") or "")
            elif "CONTATO" in label_u:
                id_valores[eid] = str(payload.get("contato") or "")
            elif "PARCEIRO" in label_u or "SAP" in label_u:
                id_valores[eid] = str(payload.get("codigo_sap") or "")
            elif "CARACTER" in label_u or "QUANTIDADE DE BLOCOS" in label_u:
                id_valores[eid] = caract

        preenchidos: List[str] = []
        for eid, valor in id_valores.items():
            if valor is None or valor == "":
                continue
            if self._fill_id(eid, str(valor)):
                preenchidos.append(f"{eid}={valor}")

        mapa_path = Path(settings.BASE_DIR) / "tmp_vtop_mapa_etapa_cadastro.json"
        mapa_path.write_text(
            json.dumps(
                {
                    "obra_id": obra_id,
                    "header": dump.get("header"),
                    "itens": dump.get("itens"),
                    "valores_enviados": id_valores,
                    "preenchidos": preenchidos,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.state.extras["cadastro_campos_ok"] = preenchidos
        self.state.extras["cadastro_mapa"] = str(mapa_path)

        # Carta/fachada são itens do checklist: sem eles a V.tal recusa a validação.
        # Anexa por padrão; só pula se o payload desligar explicitamente.
        anexar = payload.get("anexar_arquivos", payload.get("com_anexos", True))
        if not anexar:
            logger.info("[VTOP] Anexos desligados no payload — carta/fachada não enviadas.")
        if anexar:
            self._set(VtopStatus.UPLOADING, "Tentando anexar carta/fachada…", step="upload")
            try:
                self._anexar_se_possivel(
                    "CARTA DE AUTORIZAÇÃO",
                    payload.get("link_carta") or "",
                    "carta_",
                    info="Carta sindico",
                )
                self._anexar_se_possivel(
                    "FOTOS DA FAIXADA",
                    payload.get("link_fachada") or "",
                    "fachada_",
                    info="Foto fachada",
                )
            except Exception as exc:
                logger.exception("[VTOP] Falha em anexos (não aborta): %s", exc)
                self.state.extras.setdefault("anexos_falha", []).append(str(exc))
                if getattr(settings, "VTOP_ANEXO_OBRIGATORIO", False):
                    raise

        self._set(
            VtopStatus.FILLING_CADASTRO,
            f"Cadastro preenchido ({len(preenchidos)} campos) obra={obra_id}.",
            step="cadastro",
        )

    def _anexar_se_possivel(self, label_hint: str, url: str, prefix: str, info: str = "") -> bool:
        """
        Anexa via popup addDocFoto:
          ícone fa-square-plus → #doc_foto_item + #informacoes + #btn_sub_foto → POST AddDocFoto
        """
        assert self.page is not None
        page = self.page
        if not url:
            logger.warning("[VTOP] Sem URL para anexar (%s)", label_hint)
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:url_vazia")
            return False

        path = baixar_anexo_temporario(url, prefix=prefix)
        if not path:
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:download_falhou")
            return False
        # Portal rejeita NOT_IMAGE; jfif → jpg (só marca temp se for conversão/download)
        path_orig = path
        path = self._garantir_imagem_jpg(path)
        if path != path_orig and not os.path.isfile(url) and not str(url).lower().startswith("file:"):
            # path_orig era download temp
            self._temp_files.append(path_orig)
        elif path == path_orig and not os.path.isfile(url) and not str(url).lower().startswith("file:"):
            self._temp_files.append(path)

        hint_u = label_hint.upper()
        candidatos = page.locator(".item_checklist")
        alvo = None
        for i in range(candidatos.count()):
            txt = (candidatos.nth(i).inner_text() or "").upper()
            # Match por palavra-chave do tipo de anexo (acentos/encoding variáveis no DOM)
            if "CARTA" in hint_u:
                if "CARTA" in txt and "AUTORIZA" in txt:
                    alvo = candidatos.nth(i)
                    break
            elif "FOTO" in hint_u or "FAI" in hint_u or "FACHADA" in hint_u:
                if "FOTO" in txt and ("FAI" in txt or "FACHADA" in txt):
                    alvo = candidatos.nth(i)
                    break
            elif hint_u[:12] in txt:
                alvo = candidatos.nth(i)
                break
        if alvo is None:
            logger.warning("[VTOP] Item checklist não encontrado: %s", label_hint)
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:item_nao_encontrado")
            return False

        plus = alvo.locator("i.fa-square-plus[onclick*='addDocFoto'], i[onclick*='addDocFoto']")
        if plus.count() == 0:
            plus = alvo.locator("i.fa-square-plus")
        if plus.count() == 0:
            logger.warning("[VTOP] Ícone addDocFoto não encontrado em: %s", label_hint)
            self.state.extras.setdefault("anexos_falha", []).append(f"{label_hint}:icone_nao_encontrado")
            return False

        # Já tem arquivo vinculado? Não reenvia (evita duplicar carta/fachada).
        ja_tem = alvo.evaluate(
            """(el) => {
              if (el.querySelector('img[src*="doc"], img[src*="foto"], img.thumb, a[href*="Download"], a[href*="download"]'))
                return true;
              if (el.querySelector('i.fa-file, i.fa-file-image, i.fa-paperclip, i.fa-image'))
                return true;
              const txt = (el.innerText || '').toUpperCase();
              if (txt.includes('.JPG') || txt.includes('.JPEG') || txt.includes('.PNG') ||
                  txt.includes('.JFIF') || txt.includes('.PDF') || txt.includes('CARTA_') ||
                  txt.includes('FACHADA_'))
                return true;
              // contador visual comum: vários ícones de lixeira (remove doc) = já anexado
              if (el.querySelectorAll('i.fa-trash, i.fa-times, [onclick*="removeDoc"], [onclick*="RemoveDoc"]').length > 0)
                return true;
              return false;
            }"""
        )
        if ja_tem:
            logger.info("[VTOP] Anexo já presente — pulando upload (%s)", label_hint)
            self.state.extras.setdefault("anexos_pulados", []).append(label_hint)
            return True

        def _aceitar(dialog) -> None:
            try:
                logger.info("[VTOP] Dialog anexo: %s", dialog.message)
                dialog.accept()
            except Exception as exc:
                logger.warning("[VTOP] Dialog anexo já tratado: %s", exc)

        page.once("dialog", _aceitar)
        try:
            plus.first.click()
            page.locator("#doc_foto_item").wait_for(state="visible", timeout=10_000)
        except Exception as exc:
            logger.warning(
                "[VTOP] Popup de anexo não abriu (%s) — pulando upload: %s",
                label_hint,
                exc,
            )
            self.state.extras.setdefault("anexos_pulados", []).append(f"{label_hint}:popup")
            # tenta fechar lixo do popup
            try:
                if page.locator("#popup_foto").count() and page.locator("#popup_foto").is_visible():
                    page.locator("#b_cancelarNovaEstacao").click(timeout=2000)
            except Exception:
                pass
            return False

        page.locator("#doc_foto_item").set_input_files(path)
        legenda = (info or prefix.rstrip("_") or "anexo")[:30]
        page.locator("#informacoes").fill(legenda)
        btn_sub = page.locator("#btn_sub_foto")
        try:
            btn_sub.click(force=True, timeout=15_000)
        except Exception:
            # Popup do SmartRiser às vezes trava o click nativo
            page.evaluate(
                """() => {
                  const b = document.getElementById('btn_sub_foto');
                  if (b) b.click();
                }"""
            )
        page.wait_for_timeout(2500)
        # fecha popup se ainda aberto
        if page.locator("#popup_foto").count() and page.locator("#popup_foto").is_visible():
            try:
                page.locator("#b_cancelarNovaEstacao").click(timeout=2000)
            except Exception:
                pass
        logger.info("[VTOP] Anexo enviado (%s): %s", label_hint, path)
        self.state.extras.setdefault("anexos_ok", []).append(label_hint)
        return True

    def _garantir_imagem_jpg(self, path: str) -> str:
        """Converte jfif/webp/etc. para .jpg temporário quando necessário."""
        p = Path(path)
        suf = p.suffix.lower()
        if suf in {".jpg", ".jpeg", ".png", ".bmp"}:
            return path
        try:
            from PIL import Image

            img = Image.open(path)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            fd, out = tempfile.mkstemp(prefix="vtop_img_", suffix=".jpg")
            os.close(fd)
            img.save(out, format="JPEG", quality=90)
            self._temp_files.append(out)
            logger.info("[VTOP] Convertido anexo %s → %s", path, out)
            return out
        except Exception:
            logger.exception("[VTOP] Falha ao converter imagem %s", path)
            return path

    def _aceitar_dialogs(self) -> None:
        """Handler permanente: aceita confirms (mapa/validar) sem erro se já tratado."""
        assert self.page is not None
        if getattr(self, "_dialog_handler_installed", False):
            return

        def _on_dialog(dialog) -> None:
            try:
                logger.info("[VTOP] Dialog: %s", dialog.message)
                dialog.accept()
            except Exception as exc:
                logger.warning("[VTOP] Dialog já tratado/ignorado: %s", exc)

        self.page.on("dialog", _on_dialog)
        self._dialog_handler_installed = True

    def _passo_salvar_disquete(self) -> None:
        """Salva a etapa atual via #btn_salvarEtapa → salvarEtapa(..., false)."""
        assert self.page is not None
        self._set(VtopStatus.SAVING, "Salvando etapa Cadastro (#btn_salvarEtapa)…", step="salvar")
        page = self.page
        self._aceitar_dialogs()
        btn = page.locator("#btn_salvarEtapa")
        if btn.count() == 0:
            raise RuntimeError("#btn_salvarEtapa não encontrado.")
        if not btn.first.is_visible():
            logger.warning("[VTOP] #btn_salvarEtapa não visível; tentando clique mesmo assim.")
        btn.first.click(force=True)
        try:
            page.wait_for_function(
                """() => {
                  const el = document.querySelector('#carregando, .carregando, #atualizando');
                  if (!el) return true;
                  const cs = getComputedStyle(el);
                  return cs.display === 'none' || cs.visibility === 'hidden' || el.offsetParent === null;
                }""",
                timeout=30_000,
            )
        except Exception:
            page.wait_for_timeout(2500)
        page.wait_for_timeout(1000)
        self._set(VtopStatus.SAVING, "Etapa Cadastro salva.", step="salvar")

    def _passo_validar(self) -> None:
        """Valida etapa e avança (#btn_validarEtapa → confirm + salvarEtapa valida=true)."""
        assert self.page is not None
        self._set(VtopStatus.VALIDATING, "Validando etapa Cadastro…", step="validar")
        page = self.page
        self._aceitar_dialogs()
        btn = page.locator("#btn_validarEtapa")
        if btn.count() == 0:
            raise RuntimeError("#btn_validarEtapa não encontrado.")
        etapa_antes = ler_etapa_obra_page(page)
        mensagens: List[str] = []

        def _registrar(dialog) -> None:
            mensagens.append(dialog.message)

        page.on("dialog", _registrar)
        try:
            btn.first.click(force=True)
            page.wait_for_timeout(4000)
        finally:
            page.remove_listener("dialog", _registrar)
        etapa = ler_etapa_obra_page(page)
        self.state.extras["obra_etapa_apos_validar"] = etapa
        self.state.extras["validar_mensagens"] = mensagens[:5]
        obra_id = str(self.state.extras.get("obra_id") or self._detectar_obra_id() or "")
        if obra_id and etapa is not None:
            self._gravar_vinculo_obra(obra_id, etapa=etapa)
        if etapa_antes is not None and etapa is not None and etapa <= etapa_antes:
            # Ex.: "Todos os itens desse checklist devem ser preenchidos!" (faltou anexo)
            recusa = next((msg for msg in mensagens if "?" not in msg), "") or "etapa não avançou"
            raise RuntimeError(
                f"Cadastro salvo na obra {obra_id}, mas a V.tal recusou a validação: {recusa}"
            )
        self._set(VtopStatus.VALIDATING, f"Etapa validada (obra.etapa={etapa}).", step="validar")


# Instância de processo (1 browser V.top por worker Django/local)
_service_lock = threading.Lock()
_service: Optional[VtopSmartRiserService] = None


def get_vtop_service() -> VtopSmartRiserService:
    global _service
    with _service_lock:
        if _service is None:
            _service = VtopSmartRiserService()
        return _service
