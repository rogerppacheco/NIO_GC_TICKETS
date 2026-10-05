from __future__ import annotations

import re

from django import forms

from .forms import MultipleFileField, MultipleFileInput
from .models import Comunicado

EXTENSOES_ANEXO = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
)
TAMANHO_MAX_ANEXO = 20 * 1024 * 1024
MAX_ANEXOS_POR_ENVIO = 8
ACCEPT_ANEXO = ",".join(EXTENSOES_ANEXO)


class ComunicadoForm(forms.ModelForm):
    enviar_whatsapp = forms.BooleanField(
        label="Enviar por WhatsApp ao salvar",
        required=False,
    )
    whatsapp_destino = forms.CharField(
        label="WhatsApp ou grupo",
        required=False,
        widget=forms.Select(),
    )
    whatsapp_numero = forms.CharField(
        label="Número",
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={"inputmode": "tel", "placeholder": "31999999999", "autocomplete": "off"}
        ),
    )
    anexos = MultipleFileField(
        label="Arquivos",
        required=False,
        help_text=(
            "PDF, Word, Excel, PowerPoint ou imagem. "
            f"Até {MAX_ANEXOS_POR_ENVIO} arquivos por vez, 20 MB cada."
        ),
        widget=MultipleFileInput(
            attrs={"accept": ACCEPT_ANEXO, "multiple": True}
        ),
    )

    class Meta:
        model = Comunicado
        fields = ["titulo", "corpo", "publico", "ativo"]
        widgets = {
            "titulo": forms.TextInput(attrs={"maxlength": 180}),
            "corpo": forms.Textarea(attrs={"rows": 14}),
        }
        help_texts = {
            "publico": (
                "Parceiros confirmam no login do PDV. Equipe confirma no login interno. "
                "Todos exige confirmação dos dois públicos."
            ),
            "ativo": "Desmarque para arquivar. Comunicados inativos não bloqueiam o login.",
        }

    def __init__(self, *args, destinos=None, grupos_ao_vivo=None, **kwargs):
        self._destinos = {item.pk: item for item in (destinos or []) if item.ativo}
        super().__init__(*args, **kwargs)
        self.fields["whatsapp_destino"].widget.choices = self._opcoes_whatsapp(
            grupos_ao_vivo or []
        )
        self.fields["enviar_whatsapp"].help_text = (
            "O texto e os arquivos vão para o número ou grupo escolhido. "
            "O comunicado continua no portal."
        )

    def _opcoes_whatsapp(self, grupos_ao_vivo: list) -> list:
        grupos = []
        numeros = []
        for destino in self._destinos.values():
            rotulo = destino.nome
            parceiro = getattr(destino, "parceiro", None)
            if destino.parceiro_id and parceiro:
                rotulo = f"{destino.nome} · {parceiro.nome}"
            opcao = (f"dest:{destino.pk}", rotulo)
            if getattr(destino, "tipo", "") == "grupo":
                grupos.append(opcao)
            else:
                numeros.append(opcao)
        ao_vivo = []
        for grupo in grupos_ao_vivo:
            jid = str(grupo.get("jid") or "").strip()
            nome = str(grupo.get("name") or "Grupo").replace("|", " ").strip()
            if "@g.us" not in jid:
                continue
            ao_vivo.append((f"live:{jid}|{nome[:150]}", nome))
        escolhas: list = [("", "Selecione")]
        if grupos:
            escolhas.append(("Grupos cadastrados", grupos))
        if numeros:
            escolhas.append(("Números cadastrados", numeros))
        if ao_vivo:
            escolhas.append(("Grupos do WhatsApp conectado", ao_vivo))
        escolhas.append(("numero", "Outro número"))
        if self.is_bound:
            atual = (self.data.get(self.add_prefix("whatsapp_destino")) or "").strip()
            if atual.startswith("live:") and not self._opcao_existe(escolhas, atual):
                nome = atual.split("|", 1)[-1] or atual
                escolhas.insert(-1, (atual, nome[:150]))
        return escolhas

    def _opcao_existe(self, escolhas, valor: str) -> bool:
        for item in escolhas:
            if isinstance(item[1], (list, tuple)):
                if any(opcao[0] == valor for opcao in item[1]):
                    return True
            elif item[0] == valor:
                return True
        return False

    def clean(self):
        data = super().clean()
        if not data.get("enviar_whatsapp"):
            return data
        destino = (data.get("whatsapp_destino") or "").strip()
        if destino == "numero":
            numero = re.sub(r"\D", "", data.get("whatsapp_numero") or "")
            if not 10 <= len(numero) <= 15:
                self.add_error(
                    "whatsapp_numero",
                    "Informe o número com DDD. Ex.: 31999999999.",
                )
            else:
                data["whatsapp_jid"] = numero
                data["whatsapp_nome"] = f"WhatsApp {numero}"
            return data
        if destino.startswith("dest:"):
            try:
                pk = int(destino.split(":", 1)[1])
            except (TypeError, ValueError):
                pk = 0
            cadastrado = self._destinos.get(pk)
            jid = (getattr(cadastrado, "jid", "") or "").strip() if cadastrado else ""
            if not cadastrado or not jid:
                self.add_error("whatsapp_destino", "Escolha um WhatsApp ou grupo da sua lista.")
            else:
                data["whatsapp_jid"] = jid
                data["whatsapp_nome"] = cadastrado.nome
            return data
        if destino.startswith("live:"):
            resto = destino[5:]
            jid, _, nome = resto.partition("|")
            jid = jid.strip()
            nome = (nome or "Grupo WhatsApp").strip()
            if "@g.us" not in jid:
                self.add_error("whatsapp_destino", "Escolha um grupo válido.")
            else:
                data["whatsapp_jid"] = jid
                data["whatsapp_nome"] = nome[:150]
            return data
        self.add_error("whatsapp_destino", "Escolha o WhatsApp ou o grupo.")
        return data

    def clean_anexos(self):
        bruto = self.cleaned_data.get("anexos") or []
        arquivos = [arquivo for arquivo in bruto if arquivo]
        if len(arquivos) > MAX_ANEXOS_POR_ENVIO:
            raise forms.ValidationError(
                f"Envie no máximo {MAX_ANEXOS_POR_ENVIO} arquivos por vez."
            )
        for arquivo in arquivos:
            nome = (getattr(arquivo, "name", "") or "").lower()
            if not any(nome.endswith(ext) for ext in EXTENSOES_ANEXO):
                raise forms.ValidationError(
                    f"Formato não aceito ({arquivo.name}). "
                    "Use PDF, Word, Excel, PowerPoint ou imagem."
                )
            tamanho = getattr(arquivo, "size", 0) or 0
            if tamanho > TAMANHO_MAX_ANEXO:
                raise forms.ValidationError(f"{arquivo.name} passa de 20 MB.")
        return arquivos
