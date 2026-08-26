from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .demanda_campos import LABELS_SIMPLES, LABELS_POR_TIPO, campos_resposta, montar_texto_retorno, schema_tipo
from .models import (
    Anexo,
    ContatoParceiro,
    Mascara,
    Mensagem,
    Parceiro,
    PerfilStaff,
    StatusTicket,
    Ticket,
    TipoDemanda,
)


MOTIVO_REPARO_CHOICES = [
    ("", "Selecione"),
    ("Internet não funciona (total)", "Internet não funciona (total)"),
    ("Internet com lentidão", "Internet com lentidão"),
    ("outro", "Outra (descreva abaixo)"),
]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Aceita um ou vários arquivos (FileField padrão quebra com getlist)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
            # Sem arquivos e campo opcional: lista vazia (não None).
            if not result and not self.required:
                return []
            return result
        return [single_file_clean(data, initial)]


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Usuário", widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Senha", widget=forms.PasswordInput)

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        from .acesso import tem_acesso_interno

        if not tem_acesso_interno(user):
            raise forms.ValidationError(
                "Este login não tem acesso ao NIO GC Tickets. "
                "Use um usuário criado em Especialistas ou Meu perfil.",
                code="sem_acesso",
            )


class ParceiroForm(forms.ModelForm):
    class Meta:
        model = Parceiro
        fields = [
            "codigo_pdv",
            "nome",
            "ativo",
            "especialista",
            "token_acesso",
        ]
        help_texts = {
            "token_acesso": "Um único token para todos os contatos deste PDV (opcional).",
            "especialista": "Quem trata as demandas deste PDV.",
        }
        widgets = {
            "token_acesso": forms.TextInput(
                attrs={
                    "placeholder": "Digite ou escolha uma sugestão",
                    "autocomplete": "off",
                    "class": "mono",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .acesso import qs_equipe

        campo = self.fields["especialista"]
        campo.queryset = qs_equipe()
        campo.required = False
        campo.empty_label = "Sem especialista"
        campo.label_from_instance = lambda u: (
            f"{(u.get_full_name() or u.username).strip()} · {u.perfil_staff.get_papel_display()}"
            if getattr(u, "perfil_staff", None)
            else (u.get_full_name() or u.username)
        )


class EspecialistaForm(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150)
    username = forms.CharField(label="Usuário (login)", max_length=150)
    email = forms.EmailField(label="E-mail", required=False)
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput,
        required=False,
        help_text="Deixe em branco para manter a senha atual.",
    )
    fte = forms.DecimalField(
        label="FTE",
        max_digits=3,
        decimal_places=2,
        required=False,
        initial=Decimal("1.00"),
        min_value=Decimal("0.01"),
        max_value=Decimal("9.99"),
        help_text="1.00 representa tempo integral e 0.5 representa meio período.",
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "max": "9.99"}),
    )
    is_active = forms.BooleanField(label="Ativo", required=False, initial=True)
    eh_admin = forms.BooleanField(
        label="Admin — vê todos os tickets",
        required=False,
        help_text=(
            "Se marcado, esta pessoa vê a fila inteira, todos os parceiros e a equipe. "
            "Se desmarcado, vê só os PDVs em que é o especialista."
        ),
    )
    whatsapp = forms.CharField(
        label="WhatsApp",
        max_length=40,
        required=False,
        help_text="Número com DDI. Especialista recebe as máscaras neste número, não nos grupos dos PDVs.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance and "initial" not in kwargs:
            perfil = getattr(instance, "perfil_staff", None)
            kwargs["initial"] = {
                "first_name": instance.first_name,
                "username": instance.username,
                "email": instance.email,
                "is_active": instance.is_active,
                "eh_admin": bool(
                    perfil and perfil.papel == PerfilStaff.Papel.GESTOR
                ),
                "fte": perfil.fte if perfil else Decimal("1.00"),
                "whatsapp": perfil.whatsapp if perfil else "",
            }
        super().__init__(*args, **kwargs)
        if instance is None:
            self.fields["password"].required = True
            self.fields["password"].help_text = "Senha inicial do especialista."
            self.fields["password"].widget = forms.PasswordInput()

    def clean_username(self):
        User = get_user_model()
        username = (self.cleaned_data.get("username") or "").strip()
        qs = User.objects.filter(username__iexact=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        outro = qs.first()
        if outro:
            raise forms.ValidationError(
                f"Já existe um usuário com o login “{outro.username}”. "
                "Esse é outro acesso (não este especialista). "
                "Se for o seu usuário de admin, altere em Meu perfil."
            )
        return username

    def clean(self):
        cleaned = super().clean()
        if not self.instance:
            return cleaned

        perfil = getattr(self.instance, "perfil_staff", None)
        if not perfil or perfil.papel != PerfilStaff.Papel.GESTOR:
            return cleaned
        outros_admins = PerfilStaff.objects.filter(
            papel=PerfilStaff.Papel.GESTOR
        ).exclude(user_id=self.instance.pk)
        if outros_admins.exists():
            return cleaned
        if not cleaned.get("eh_admin"):
            self.add_error(
                "eh_admin",
                "Não é possível remover o último admin. Marque outra pessoa como admin antes.",
            )
        if not cleaned.get("is_active"):
            self.add_error(
                "is_active",
                "Não é possível inativar o último admin.",
            )
        return cleaned

    def save(self):
        User = get_user_model()

        dados = self.cleaned_data
        papel = (
            PerfilStaff.Papel.GESTOR
            if dados.get("eh_admin")
            else PerfilStaff.Papel.ESPECIALISTA
        )
        if self.instance:
            user = self.instance
            user.first_name = dados["first_name"]
            user.username = dados["username"]
            user.email = dados.get("email") or ""
            user.is_active = dados.get("is_active", True)
            if dados.get("password"):
                user.set_password(dados["password"])
            user.is_staff = True
            user.save()
        else:
            user = User.objects.create_user(
                username=dados["username"],
                password=dados["password"],
                first_name=dados["first_name"],
                email=dados.get("email") or "",
                is_staff=True,
                is_active=True,
            )
        perfil, _ = PerfilStaff.objects.update_or_create(
            user=user,
            defaults={
                "papel": papel,
                "fte": dados.get("fte") or Decimal("1.00"),
                "whatsapp": (dados.get("whatsapp") or "").strip(),
            },
        )
        user.perfil_staff = perfil
        return user


class StaffPerfilForm(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150)
    username = forms.CharField(
        label="Usuário (login)",
        max_length=150,
        help_text="Este login precisa ser exclusivo neste banco. Não use o de outra conta.",
    )
    email = forms.EmailField(label="E-mail", required=False)
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput,
        required=False,
        help_text="Deixe em branco para manter a senha atual.",
    )
    whatsapp = forms.CharField(
        label="WhatsApp",
        max_length=40,
        required=False,
        help_text="Se você não for admin, as máscaras de Gestão chegam neste número.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance and "initial" not in kwargs:
            kwargs["initial"] = {
                "first_name": instance.first_name,
                "username": instance.username,
                "email": instance.email,
                "whatsapp": getattr(getattr(instance, "perfil_staff", None), "whatsapp", "") or "",
            }
        super().__init__(*args, **kwargs)

    def clean_username(self):
        User = get_user_model()
        username = (self.cleaned_data.get("username") or "").strip()
        qs = User.objects.filter(username__iexact=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"O login “{username}” já pertence a outra conta. "
                "Se for a sua, saia e entre com esse usuário. "
                "Não copie o login de outra pessoa nesta tela."
            )
        return username

    def save(self):
        user = self.instance
        dados = self.cleaned_data
        user.first_name = dados["first_name"]
        user.username = dados["username"]
        user.email = dados.get("email") or ""
        if dados.get("password"):
            user.set_password(dados["password"])
        user.save()
        perfil = getattr(user, "perfil_staff", None)
        if perfil is not None:
            perfil.whatsapp = (dados.get("whatsapp") or "").strip()
            perfil.save(update_fields=["whatsapp"])
        return user


class ContatoParceiroForm(forms.ModelForm):
    class Meta:
        model = ContatoParceiro
        fields = ["nome", "email", "telefone", "cargo", "ativo"]
        labels = {
            "telefone": "WhatsApp / telefone",
        }

    def clean_ativo(self):
        # checkbox: se ausente no POST, fica False
        return self.data.get("ativo") in {"on", "true", "1", True, "True"}


class TicketCreateForm(forms.ModelForm):
    evidencias = MultipleFileField(
        required=False,
        label="Evidências (anexo)",
    )
    motivo_reparo = forms.ChoiceField(
        required=False,
        choices=MOTIVO_REPARO_CHOICES,
        label="Solicitação",
    )

    class Meta:
        model = Ticket
        fields = [
            "parceiro",
            "tipo",
            "solicitante_nome",
            "solicitante_contato",
            "pedido",
            "documento_cliente",
            "tt",
            "tt_vendedor",
            "tt_backoffice",
            "cep",
            "logradouro",
            "numero_fachada",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "endereco_completo",
            "nome_cliente",
            "data_instalacao",
            "data_desejada",
            "turno",
            "data_alternativa",
            "turno_alternativo",
            "descricao",
            "observacoes",
        ]
        widgets = {
            "tipo": forms.Select(attrs={"id": "id_tipo", "class": "tipo-demanda"}),
            "data_desejada": forms.DateInput(attrs={"type": "date"}),
            "data_instalacao": forms.DateInput(attrs={"type": "date"}),
            "data_alternativa": forms.DateInput(attrs={"type": "date"}),
            "descricao": forms.Textarea(attrs={"rows": 3, "placeholder": "Descreva em poucas linhas"}),
            "observacoes": forms.TextInput(attrs={"placeholder": "Ex.: Etapa 3 — consulta CPF"}),
            "uf": forms.TextInput(attrs={"maxlength": "2", "placeholder": "UF"}),
            "endereco_completo": forms.TextInput(
                attrs={"readonly": True, "placeholder": "Preenchido pelo CEP"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "parceiro" in self.fields:
            self.fields["parceiro"].queryset = Parceiro.objects.filter(ativo=True)
            self.fields["parceiro"].empty_label = "Selecione o PDV"
        for name, label in LABELS_SIMPLES.items():
            if name in self.fields:
                self.fields[name].label = label
                self.fields[name].required = False
        self.fields["tipo"].required = True
        self.fields["tipo"].choices = [("", "Selecione o tipo...")] + list(TipoDemanda.choices)
        if "parceiro" in self.fields:
            self.fields["parceiro"].required = True
        # Placeholder amigável por campo
        if "pedido" in self.fields:
            self.fields["pedido"].widget.attrs.setdefault("placeholder", "Nº do pedido/OS")
        if "documento_cliente" in self.fields:
            self.fields["documento_cliente"].widget.attrs.setdefault("placeholder", "Somente números")
        if "tt" in self.fields:
            self.fields["tt"].widget.attrs.setdefault("placeholder", "Número da TT")
        if "tt_vendedor" in self.fields:
            self.fields["tt_vendedor"].widget.attrs.setdefault(
                "placeholder", "TT do vendedor"
            )
        if "tt_backoffice" in self.fields:
            self.fields["tt_backoffice"].widget.attrs.setdefault(
                "placeholder", "TT do backoffice de cadastro"
            )
        if "solicitante_contato" in self.fields:
            self.fields["solicitante_contato"].widget.attrs.setdefault(
                "placeholder", "DDD + número do cliente"
            )
        if "nome_cliente" in self.fields:
            self.fields["nome_cliente"].widget.attrs.setdefault(
                "placeholder", "Nome completo do cliente"
            )
        # Label padrão de documento: obrigatório só quando o schema exige
        if "documento_cliente" in self.fields:
            self.fields["documento_cliente"].label = "CPF / CNPJ"
        self.order_fields(
            [
                "parceiro",
                "tipo",
                "pedido",
                "documento_cliente",
                "nome_cliente",
                "solicitante_nome",
                "solicitante_contato",
                "tt",
                "tt_vendedor",
                "tt_backoffice",
                "cep",
                "logradouro",
                "numero_fachada",
                "complemento",
                "bairro",
                "cidade",
                "uf",
                "endereco_completo",
                "data_instalacao",
                "data_desejada",
                "turno",
                "data_alternativa",
                "turno_alternativo",
                "motivo_reparo",
                "descricao",
                "observacoes",
                "evidencias",
            ]
        )

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        if not tipo:
            return cleaned
        cfg = schema_tipo(tipo)
        labels = {**LABELS_SIMPLES, **LABELS_POR_TIPO.get(tipo, {})}
        for campo in cfg["obrigatorios"]:
            if campo == "evidencias":
                files = cleaned.get("evidencias") or []
                if not files and self.files:
                    files = self.files.getlist("evidencias")
                if not files:
                    self.add_error("evidencias", "Anexe ao menos uma evidência.")
                continue
            valor = cleaned.get(campo)
            if valor in (None, ""):
                label = labels.get(campo, campo)
                self.add_error(campo, f"{label} é obrigatório para este tipo.")
        if tipo == TipoDemanda.REPARO:
            motivo = (cleaned.get("motivo_reparo") or "").strip()
            texto = (cleaned.get("descricao") or "").strip()
            if motivo == "outro":
                if not texto:
                    self.add_error("descricao", "Descreva a solicitação.")
            elif motivo:
                cleaned["descricao"] = motivo
        return cleaned


class TicketPublicCreateForm(TicketCreateForm):
    class Meta(TicketCreateForm.Meta):
        fields = [f for f in TicketCreateForm.Meta.fields if f != "parceiro"]


class TicketTreatForm(forms.ModelForm):
    use_required_attribute = False
    complemento_retorno = forms.CharField(
        required=False,
        label="Complemento do retorno",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "Texto extra opcional para o parceiro",
            }
        ),
        help_text="Soma-se aos campos específicos acima no RETORNO.",
    )

    class Meta:
        model = Ticket
        fields = [
            "tipo",
            "status",
            "prioridade",
            "atendente",
            "solicitante_contato",
            "solicitante_nome",
            "resultado_status",
            "nota_interna",
            "destino_encaminhamento",
        ]
        widgets = {
            "tipo": forms.Select(
                attrs={"id": "id_tipo_tratamento", "data-tipo-demanda": "1"}
            ),
            "resultado_status": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: SENHA RESETADA / ENDEREÇO LOCALIZADO..."
                }
            ),
            "solicitante_contato": forms.TextInput(
                attrs={"placeholder": "WhatsApp / telefone para retorno"}
            ),
            "nota_interna": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "tipo": "Tipo da demanda",
            "status": "Situação na fila",
            "solicitante_contato": "WhatsApp / telefone",
            "solicitante_nome": "Contato / solicitante",
            "resultado_status": "STATUS",
            "nota_interna": "DETALHES (interno)",
        }
        help_texts = {
            "tipo": "Altere se a demanda foi aberta no tipo errado. Ao salvar, campos e máscaras se atualizam.",
            "status": "Obrigatório ao salvar. Abrir o modal não muda a fila.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        situacoes = [
            (valor, rotulo)
            for valor, rotulo in StatusTicket.choices
            if valor != StatusTicket.NOVO
        ]
        campo_status = self.fields["status"]
        campo_status.required = True
        campo_status.error_messages["required"] = (
            "Escolha a situação na fila. Depois de salvar, o ticket não pode permanecer como Novo."
        )
        campo_status.error_messages["invalid_choice"] = (
            "Escolha a situação na fila. Depois de salvar, o ticket não pode permanecer como Novo."
        )
        if getattr(self.instance, "status", None) == StatusTicket.NOVO:
            campo_status.choices = [("", "Selecione a situação")] + situacoes
            if not self.is_bound:
                campo_status.initial = ""
        else:
            campo_status.choices = situacoes
        # Em POST, usa o tipo enviado para montar os campos de resposta
        tipo = self.instance.tipo
        if self.is_bound:
            tipo = self.data.get("tipo") or tipo
        self.campos_resposta_defs = campos_resposta(tipo)
        dados = self.instance.retorno_dados or {}
        for campo in self.campos_resposta_defs:
            name = campo["name"]
            if campo.get("widget") == "textarea":
                widget = forms.Textarea(
                    attrs={
                        "rows": 3,
                        "placeholder": campo.get("placeholder", ""),
                    }
                )
            else:
                widget = forms.TextInput(
                    attrs={"placeholder": campo.get("placeholder", "")}
                )
            self.fields[name] = forms.CharField(
                required=campo.get("required", False),
                label=campo["label"],
                help_text=campo.get("help", ""),
                widget=widget,
                initial=dados.get(name, ""),
            )
        # Se já havia RETORNO livre além dos campos, mostra no complemento
        montado = montar_texto_retorno(tipo, dados)
        atual = (self.instance.resposta_publica or "").strip()
        if atual and atual != montado and not self.is_bound:
            if montado and atual.startswith(montado):
                self.fields["complemento_retorno"].initial = atual[len(montado) :].strip()
            elif not dados:
                self.fields["complemento_retorno"].initial = atual

    def clean_status(self):
        status = self.cleaned_data.get("status")
        if not status or status == StatusTicket.NOVO:
            raise forms.ValidationError(
                "Escolha a situação na fila. Depois de salvar, o ticket não pode permanecer como Novo."
            )
        return status

    def retorno_dados_limpos(self) -> dict:
        dados = {}
        for campo in self.campos_resposta_defs:
            name = campo["name"]
            valor = (self.cleaned_data.get(name) or "").strip()
            if valor:
                dados[name] = valor
        return dados

    def save(self, commit=True):
        instance = super().save(commit=False)
        dados = self.retorno_dados_limpos()
        instance.retorno_dados = dados
        instance.resposta_publica = montar_texto_retorno(
            instance.tipo,
            dados,
            self.cleaned_data.get("complemento_retorno") or "",
        )
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class MensagemForm(forms.ModelForm):
    class Meta:
        model = Mensagem
        fields = ["corpo", "interno"]
        widgets = {"corpo": forms.Textarea(attrs={"rows": 3, "placeholder": "Escreva a mensagem..."})}
        labels = {"interno": "Nota interna (não visível ao parceiro)"}


class AnexoForm(forms.ModelForm):
    class Meta:
        model = Anexo
        fields = ["arquivo"]


class MascaraForm(forms.ModelForm):
    class Meta:
        model = Mascara
        fields = ["nome", "destino", "tipos", "template", "ativo"]
        widgets = {
            "template": forms.Textarea(attrs={"rows": 10, "class": "mono"}),
            "tipos": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: prioridade_elite,agendar_reagendar (vazio = todos)"
                }
            ),
        }


class FilaFiltroForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Busca",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Protocolo, pedido, PDV…",
                "autocomplete": "off",
                "class": "fila-search",
            }
        ),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Todos status")] + list(StatusTicket.choices),
        widget=forms.Select(attrs={"class": "fila-pick", "aria-label": "Status"}),
    )
    tipo = forms.ChoiceField(
        required=False,
        choices=[("", "Todos tipos")] + list(TipoDemanda.choices),
        widget=forms.Select(attrs={"class": "fila-pick", "aria-label": "Tipo"}),
    )
    parceiro = forms.ModelChoiceField(
        required=False,
        queryset=Parceiro.objects.filter(ativo=True),
        empty_label="Todos parceiros",
        widget=forms.Select(attrs={"class": "fila-pick", "aria-label": "Parceiro"}),
    )
    especialista = forms.ModelChoiceField(
        required=False,
        queryset=get_user_model().objects.none(),
        empty_label="Todos especialistas",
        label="Especialista",
        widget=forms.Select(attrs={"class": "fila-pick", "aria-label": "Especialista"}),
    )
    situacao_osab = forms.ChoiceField(
        required=False,
        choices=[("", "Todas situações OSAB")],
        widget=forms.Select(attrs={"class": "fila-pick", "aria-label": "Situação OSAB"}),
    )

    def __init__(self, *args, parceiros_qs=None, especialistas_qs=None, situacoes_osab=None, **kwargs):
        super().__init__(*args, **kwargs)
        if parceiros_qs is not None:
            self.fields["parceiro"].queryset = parceiros_qs
        if especialistas_qs is not None:
            self.fields["especialista"].queryset = especialistas_qs
        else:
            from .acesso import qs_equipe

            self.fields["especialista"].queryset = qs_equipe()
        if situacoes_osab is None:
            from gestao.models import VendaOSAB

            situacoes_osab = (
                VendaOSAB.objects.exclude(situacao="")
                .values_list("situacao", flat=True)
                .distinct()
                .order_by("situacao")
            )
        self.fields["situacao_osab"].choices = [
            ("", "Todas situações OSAB"),
            ("__sem__", "Sem OSAB"),
            *[(s, s) for s in situacoes_osab],
        ]
