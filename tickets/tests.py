from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from .acesso import eh_gestor, qs_equipe, qs_especialistas, tickets_visiveis
from .demanda_campos import contexto_demanda_para_resposta, montar_abas_tratamento
from .forms import LoginForm, MultipleFileField, ParceiroForm, TicketCreateForm, TicketTreatForm
from .models import Anexo, Mensagem, Parceiro, PerfilStaff, StatusTicket, Ticket, TipoDemanda, formatar_duracao


class MultipleFileFieldTests(SimpleTestCase):
    def test_aceita_lista_de_arquivos(self):
        campo = MultipleFileField(required=False)
        arquivo = SimpleUploadedFile("evidencia.jpeg", b"fake-image", content_type="image/jpeg")
        limpo = campo.clean([arquivo])
        self.assertEqual(len(limpo), 1)
        self.assertEqual(limpo[0].name, "evidencia.jpeg")

    def test_lista_vazia_quando_opcional(self):
        campo = MultipleFileField(required=False)
        self.assertEqual(campo.clean([]), [])


class TicketCreateEvidenciasTests(SimpleTestCase):
    def test_abrir_chamado_ti_aceita_anexo_via_getlist(self):
        """request.FILES.getlist devolve lista; FileField padrão acusava encoding."""
        arquivo = SimpleUploadedFile("10843955.jpeg", b"conteudo", content_type="image/jpeg")
        files = MultiValueDict({"evidencias": [arquivo]})
        form = TicketCreateForm(
            data={
                "tipo": TipoDemanda.ABRIR_CHAMADO_TI,
                "pedido": "10843955",
                "documento_cliente": "37161261600",
                "solicitante_nome": "WALTER",
                "tt_vendedor": "TT832209",
                "tt_backoffice": "TT832207",
                "observacoes": "AGENDAMENTO REALIZADO NAO ATRIBUI",
                "descricao": "PEDIDO NAO GEROU ATRIBUICAO",
            },
            files=files,
        )
        form.is_valid()
        self.assertNotIn("evidencias", form.errors)
        erros = " ".join(str(e) for e in form.errors.get("evidencias", []))
        self.assertNotIn("codificação", erros)
        self.assertEqual(len(form.cleaned_data.get("evidencias") or []), 1)


class FormatacaoDuracaoTests(SimpleTestCase):
    def test_formatos(self):
        self.assertEqual(formatar_duracao(None), "—")
        self.assertEqual(formatar_duracao(8), "8s")
        self.assertEqual(formatar_duracao(90), "1min 30s")
        self.assertEqual(formatar_duracao(3600), "1h 00min")


class EspecialistaAcessoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gestor", "g@x.com", "x")
        self.spec = User.objects.create_user("ana", "a@x.com", "x", is_staff=True, first_name="Ana")
        PerfilStaff.objects.create(user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv_ana = Parceiro.objects.create(
            codigo_pdv="100", nome="PDV Ana", especialista=self.spec
        )
        self.pdv_outro = Parceiro.objects.create(codigo_pdv="200", nome="PDV Outro")
        self.ticket_ana = Ticket.objects.create(
            parceiro=self.pdv_ana, tipo=TipoDemanda.RESET_SENHA, tt="TT1"
        )
        self.ticket_outro = Ticket.objects.create(
            parceiro=self.pdv_outro, tipo=TipoDemanda.STATUS_PEDIDO, pedido="99"
        )

    def test_lista_parceiros_sem_especialista_nao_quebra(self):
        from django.template import Context, Template

        html = Template(
            "{% if p.especialista %}"
            "{{ p.especialista.get_full_name|default:p.especialista.username }}"
            "{% else %}—{% endif %}"
        ).render(Context({"p": self.pdv_outro}))
        self.assertEqual(html, "—")
        html_ana = Template(
            "{% if p.especialista %}"
            "{{ p.especialista.get_full_name|default:p.especialista.username }}"
            "{% else %}—{% endif %}"
        ).render(Context({"p": self.pdv_ana}))
        self.assertIn("Ana", html_ana)

    def test_gestor_ve_todos(self):
        self.assertTrue(eh_gestor(self.gestor))
        self.assertEqual(tickets_visiveis(self.gestor).count(), 2)

    def test_especialista_ve_so_os_seus(self):
        self.assertFalse(eh_gestor(self.spec))
        qs = tickets_visiveis(self.spec)
        self.assertEqual(list(qs), [self.ticket_ana])

    def test_gestao_escopo_nao_altera_fila(self):
        from tickets.acesso import parceiros_gestao, parceiros_visiveis

        self.assertEqual(list(parceiros_visiveis(self.spec)), [self.pdv_ana])
        self.assertEqual(list(parceiros_gestao(self.spec, "meus")), [self.pdv_ana])
        self.assertEqual(list(parceiros_gestao(self.spec, "outros")), [self.pdv_outro])
        self.assertEqual(tickets_visiveis(self.spec).count(), 1)


    def test_especialista_nao_abre_ticket_alheio(self):
        self.client.force_login(self.spec)
        r = self.client.get(
            reverse("ticket_detalhe", args=[self.ticket_outro.protocolo])
        )
        self.assertEqual(r.status_code, 404)

    def test_criar_especialista_pelo_gestor(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Bruno",
                "username": "bruno",
                "email": "b@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="bruno")
        self.assertTrue(u.is_staff)
        self.assertEqual(u.perfil_staff.papel, PerfilStaff.Papel.ESPECIALISTA)
        self.assertEqual(u.perfil_staff.fte, Decimal("1.00"))

    def test_criar_especialista_com_fte_meio_periodo(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Diego",
                "username": "diego",
                "email": "d@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
                "fte": "0.50",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="diego")
        self.assertEqual(u.perfil_staff.fte, Decimal("0.50"))

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_dashboard_calcula_fte_e_tickets_por_fte(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["fte_total"], Decimal("2.00"))
        self.assertEqual(r.context["tickets_mes"], 2)
        self.assertEqual(r.context["tickets_por_fte"], 1.0)
        self.assertContains(r, "FTE da equipe")
        self.assertContains(r, "Tickets / FTE")

    def test_nao_permite_renomear_especialista_para_login_do_gestor(self):
        from .forms import EspecialistaForm

        form = EspecialistaForm(
            {
                "first_name": "Ana",
                "username": "gestor",
                "email": "a@x.com",
                "is_active": "on",
            },
            instance=self.spec,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.username, "ana")

    def test_dropdown_parceiro_mostra_equipe_deste_app(self):
        User = get_user_model()
        User.objects.create_user("DANIEL", "d@x.com", "x", is_staff=True)
        User.objects.create_user("VT35879", "v@x.com", "x", is_staff=True)
        nomes = set(qs_equipe().values_list("username", flat=True))
        self.assertEqual(nomes, {"ana", "gestor"})
        self.assertEqual(
            set(qs_especialistas().values_list("username", flat=True)),
            {"ana"},
        )
        form = ParceiroForm()
        self.assertEqual(
            set(form.fields["especialista"].queryset.values_list("username", flat=True)),
            {"ana", "gestor"},
        )

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_pagina_especialistas_mostra_gestor_e_especialista(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("especialistas"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "gestor")
        self.assertContains(r, "Ana")
        self.assertContains(r, "Admin")
        self.assertContains(r, "Editar")
        self.assertContains(r, "Excluir")
        self.assertNotContains(r, "DANIEL")

    def test_staff_de_outro_sistema_nao_e_gestor_nem_loga(self):
        User = get_user_model()
        externo = User.objects.create_user("DANIEL", "d@x.com", "x", is_staff=True)
        self.assertFalse(eh_gestor(externo))
        form = LoginForm(
            data={"username": "DANIEL", "password": "x"},
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_superuser_sem_perfil_nao_e_gestor(self):
        User = get_user_model()
        solto = User.objects.create_superuser("vt-admin", "vt@x.com", "x")
        self.assertFalse(eh_gestor(solto))

    def test_middleware_desloga_quem_nao_tem_perfil(self):
        User = get_user_model()
        externo = User.objects.create_user("VT35558", "v@x.com", "x", is_staff=True)
        self.client.force_login(externo)
        r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_perfil_nao_renomeia_para_login_de_outra_conta(self):
        from .forms import StaffPerfilForm

        form = StaffPerfilForm(
            {
                "first_name": "Admin",
                "username": "gestor",
                "email": "a@x.com",
            },
            instance=self.spec,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_promover_especialista_a_admin_ve_todos(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_editar", args=[self.spec.pk]),
            {
                "first_name": "Ana",
                "username": "ana",
                "email": "a@x.com",
                "is_active": "on",
                "eh_admin": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.perfil_staff.papel, PerfilStaff.Papel.GESTOR)
        self.assertTrue(eh_gestor(self.spec))
        self.assertEqual(tickets_visiveis(self.spec).count(), 2)

    def test_criar_especialista_como_admin(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Carla",
                "username": "carla",
                "email": "c@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
                "eh_admin": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="carla")
        self.assertEqual(u.perfil_staff.papel, PerfilStaff.Papel.GESTOR)
        self.assertTrue(eh_gestor(u))

    def test_nao_remove_ultimo_admin(self):
        from .forms import EspecialistaForm

        form = EspecialistaForm(
            {
                "first_name": "Gestor",
                "username": "gestor",
                "email": "g@x.com",
                "is_active": "on",
            },
            instance=self.gestor,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("eh_admin", form.errors)
        self.gestor.refresh_from_db()
        self.assertEqual(self.gestor.perfil_staff.papel, PerfilStaff.Papel.GESTOR)

    def test_nao_edita_a_si_mesmo_nesta_tela(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("especialista_editar", args=[self.gestor.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/perfil/", r["Location"])

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_editar_outro_admin(self):
        User = get_user_model()
        outro = User.objects.create_user(
            "bruno", "br@x.com", "x", is_staff=True, first_name="Bruno"
        )
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("especialista_editar", args=[outro.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Bruno")
        r = self.client.post(
            reverse("especialista_editar", args=[outro.pk]),
            {
                "first_name": "Bruno",
                "username": "bruno",
                "email": "br@x.com",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        outro.refresh_from_db()
        outro.perfil_staff.refresh_from_db()
        self.assertEqual(outro.perfil_staff.papel, PerfilStaff.Papel.ESPECIALISTA)
        self.assertFalse(eh_gestor(outro))

    def test_excluir_especialista(self):
        User = get_user_model()
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("especialista_excluir", args=[self.spec.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.spec.pk).exists())
        self.pdv_ana.refresh_from_db()
        self.assertIsNone(self.pdv_ana.especialista_id)

    def test_nao_exclui_a_si_mesmo(self):
        User = get_user_model()
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("especialista_excluir", args=[self.gestor.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.gestor.pk).exists())

    def test_excluir_outro_admin_quando_ha_mais_de_um(self):
        User = get_user_model()
        outro = User.objects.create_user(
            "bruno", "br@x.com", "x", is_staff=True, first_name="Bruno"
        )
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("especialista_excluir", args=[outro.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=outro.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.gestor.pk).exists())

    def test_especialista_nao_exclui(self):
        self.client.force_login(self.spec)
        r = self.client.post(reverse("especialista_excluir", args=[self.gestor.pk]))
        self.assertEqual(r.status_code, 404)


class TratamentoModalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("gestor", "g@x.com", "x")
        PerfilStaff.objects.create(user=self.user, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(codigo_pdv="100", nome="PDV")
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.RESET_SENHA, tt="TT99"
        )

    def test_primeira_aba_e_campo_da_resposta(self):
        form = TicketTreatForm(instance=self.ticket)
        abas = montar_abas_tratamento(form)
        self.assertTrue(abas[0]["principal"])
        self.assertEqual(abas[0]["id"], "senha_resetada")
        self.assertFalse(any(aba["id"] == "status" for aba in abas))

    def test_clicar_responder_inicia_cronometro_e_salvar_registra(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.resposta_iniciada_em)
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)
        self.assertContains(r, "Selecione a situação")
        self.ticket.resposta_iniciada_em = timezone.now() - timedelta(seconds=12)
        self.ticket.save(update_fields=["resposta_iniciada_em"])

        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.EM_ANALISE,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.EM_ANALISE)
        self.assertIsNotNone(self.ticket.tempo_retorno_segundos)
        self.assertGreaterEqual(self.ticket.tempo_retorno_segundos, 12)
        self.assertIn("Nio@123", self.ticket.resposta_publica)

    def test_salvar_resposta_preserva_filtro_da_fila(self):
        self.client.force_login(self.user)
        destino = reverse("fila") + "?situacao_osab=Em+Aprovisionamento&status=em_analise"
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.EM_ANALISE,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
                "next": destino,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["redirect"], destino)

    def test_abrir_modal_nao_muda_situacao_na_fila(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)

    def test_salvar_como_novo_e_rejeitado(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.NOVO,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)
        self.assertContains(r, "não pode permanecer como Novo", status_code=400)
        self.assertContains(r, "Situação na fila", status_code=400)

    def test_salvar_sem_situacao_retorna_json_claro_para_ajax(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": "",
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r.status_code, 400)
        data = r.json()
        self.assertFalse(data["ok"])
        self.assertIn("Situação", data["error"])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_modal_mostra_anexo_e_permite_copiar_mascara(self):
        from .models import Mascara

        Anexo.objects.create(
            ticket=self.ticket,
            arquivo=SimpleUploadedFile("print.jpeg", b"fake-image", content_type="image/jpeg"),
            nome_original="print.jpeg",
        )
        Mascara.objects.create(
            nome="Reset",
            destino="GC",
            tipos=TipoDemanda.RESET_SENHA,
            template="*TT:* {{tt}}",
            ativo=True,
        )
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "print.jpeg")
        self.assertContains(r, "modal-anexo-img")
        self.assertContains(r, 'data-tab="mascaras"')
        self.assertContains(r, "Copiar")
        self.assertContains(r, "*TT:* TT99")

    def test_modal_mostra_historico_de_respostas(self):
        Mensagem.objects.create(
            ticket=self.ticket,
            autor=self.user,
            autor_nome="gestor",
            corpo="Chamado 998877 aberto na TI",
            interno=False,
        )
        self.ticket.resposta_publica = "Chamado 998877 aberto na TI"
        self.ticket.resultado_status = "CHAMADO ABERTO"
        self.ticket.save(update_fields=["resposta_publica", "resultado_status"])
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-tab="historico"')
        self.assertContains(r, "Chamado 998877 aberto na TI")
        self.assertContains(r, "CHAMADO ABERTO")

    def test_salvar_sem_campo_obrigatorio_mostra_erro_no_modal(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.EM_ANALISE,
                "prioridade": self.ticket.prioridade,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Não foi possível salvar", status_code=400)
        self.assertContains(r, "Senha resetada", status_code=400)

    def test_modal_permite_alterar_tipo_da_demanda(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(r, "Aplicar tipo")
        self.assertContains(r, "id_tipo_tratamento")
        self.assertContains(r, "Situação na fila")
        self.assertNotContains(r, 'data-tab="status"')

        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "atualizar_tipo",
                "tipo": TipoDemanda.ABRIR_CHAMADO_TI,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.tipo, TipoDemanda.ABRIR_CHAMADO_TI)
        self.assertContains(r, "Nº do chamado TI")
        self.assertContains(r, "Tipo alterado")
        self.assertContains(r, "CNPJ/CPF do cliente")

    def test_abrir_chamado_ti_mostra_cpf_no_contexto(self):
        self.ticket.tipo = TipoDemanda.ABRIR_CHAMADO_TI
        self.ticket.documento_cliente = "37161261600"
        self.ticket.tt_vendedor = "Tr832209"
        self.ticket.tt_backoffice = "Tr832215"
        self.ticket.pedido = "10958838"
        self.ticket.save()
        itens = contexto_demanda_para_resposta(self.ticket)
        nomes = [i["name"] for i in itens]
        self.assertIn("documento_cliente", nomes)
        cpf = next(i for i in itens if i["name"] == "documento_cliente")
        self.assertEqual(cpf["valor"], "37161261600")
        self.assertIn("CPF", cpf["label"])


class IsolamentoAuthTests(SimpleTestCase):
    def test_schema_padrao_valido(self):
        from tickets.isolamento_auth import nome_schema

        self.assertEqual(nome_schema(), "nio_gc_tickets")

    def test_isolamento_e_noop_fora_do_postgres(self):
        from django.db import connection

        from tickets.isolamento_auth import isolar_auth_schema

        resultado = isolar_auth_schema(connection)
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado.get("motivo"), "nao_postgres")


class FilaOsabTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gestor", "g@x.com", "x")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(codigo_pdv="100", nome="PDV")
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.STATUS_PEDIDO,
            pedido="10721324",
        )
        self.storages = {
            "STORAGES": {
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
        }

    def test_fila_mostra_situacao_e_atualizacao_osab(self):
        from gestao.models import VendaOSAB

        dt_ref = timezone.now().replace(year=2026, month=8, day=21, hour=14, minute=30)
        VendaOSAB.objects.create(
            pedido="10721324",
            pdv_nome="PDV",
            situacao="Concluído",
            dt_ref=dt_ref,
        )
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SITUAÇÃO OSAB")
        self.assertContains(r, "Atualiz. OSAB")
        self.assertContains(r, "Concluído")
        self.assertContains(r, "21/08/26")
        ticket = r.context["tickets"][0]
        self.assertEqual(ticket.osab_situacao, "Concluído")
        self.assertEqual(ticket.osab_atualizacao, dt_ref)

    def test_fila_sem_osab_fica_em_branco(self):
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 200)
        ticket = r.context["tickets"][0]
        self.assertEqual(ticket.osab_situacao, "")
        self.assertIsNone(ticket.osab_atualizacao)

    def test_filtro_situacao_osab(self):
        from gestao.models import VendaOSAB

        Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.RESET_SENHA,
            pedido="99999999",
        )
        VendaOSAB.objects.create(
            pedido="10721324",
            pdv_nome="PDV",
            situacao="Em Aprovisionamento",
        )
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"), {"situacao_osab": "Em Aprovisionamento"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["tickets"]), 1)
        self.assertEqual(r.context["tickets"][0].pedido, "10721324")
        self.assertContains(r, "Todas situações OSAB")
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"), {"situacao_osab": "__sem__"})
        self.assertEqual(len(r.context["tickets"]), 1)
        self.assertEqual(r.context["tickets"][0].pedido, "99999999")

    def test_botao_responder_leva_filtros_no_next(self):
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(
                reverse("fila"),
                {"tipo": TipoDemanda.STATUS_PEDIDO, "situacao_osab": "__sem__"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-next=")
        self.assertContains(r, "tipo=status_pedido")
        self.assertContains(r, "situacao_osab=__sem__")


class SeedNioParceirosTests(TestCase):
    def test_primeira_carga_cria_parceiros_iniciais(self):
        from django.core.management import call_command

        from tickets.management.commands.seed_nio import PARCEIROS

        call_command("seed_nio")
        self.assertEqual(Parceiro.objects.count(), len(PARCEIROS))
        self.assertTrue(Parceiro.objects.filter(codigo_pdv="1068279", nome="APOLO").exists())

    def test_seed_nao_recria_parceiro_excluido(self):
        from django.core.management import call_command

        call_command("seed_nio")
        Parceiro.objects.filter(codigo_pdv="1068279").delete()
        call_command("seed_nio")
        self.assertFalse(Parceiro.objects.filter(codigo_pdv="1068279").exists())
        self.assertTrue(Parceiro.objects.filter(codigo_pdv="1068432").exists())

    def test_seed_nao_reativa_parceiro_inativo(self):
        from django.core.management import call_command

        call_command("seed_nio")
        p = Parceiro.objects.get(codigo_pdv="1068279")
        p.ativo = False
        p.save(update_fields=["ativo"])
        call_command("seed_nio")
        p.refresh_from_db()
        self.assertFalse(p.ativo)


class MascaraEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.spec = User.objects.create_user(
            "specmail", "spec@x.com", "x", is_staff=True
        )
        PerfilStaff.objects.create(user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        self.pdv = Parceiro.objects.create(
            codigo_pdv="m1",
            nome="PDV Mail",
            especialista=self.spec,
            email="pdv@x.com",
        )

    @override_settings(SMTP_HOST="smtp.test", SMTP_FROM="from@test.com")
    def test_envia_mascara_marcada(self):
        from unittest.mock import patch

        from tickets.models import Mascara
        from tickets.services import notificar_mascaras_por_email

        Mascara.objects.create(
            nome="Elite",
            destino="Grupo Elite",
            tipos=TipoDemanda.PRIORIDADE_ELITE,
            template="Pedido {{pedido}}",
            enviar_email=True,
            ativo=True,
        )
        ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.PRIORIDADE_ELITE, pedido="123"
        )
        with patch(
            "gestao.messaging.email_smtp.enviar_email_com_anexos",
            return_value=(True, ""),
        ) as send:
            n = notificar_mascaras_por_email(ticket)
        self.assertEqual(n, 1)
        destinos = send.call_args.args[0]
        self.assertIn("spec@x.com", destinos)
        self.assertIn("pdv@x.com", destinos)
        self.assertIn("123", send.call_args.kwargs["corpo_texto"])

    @override_settings(SMTP_HOST="smtp.test", SMTP_FROM="from@test.com")
    def test_ignora_mascara_de_outro_tipo(self):
        from unittest.mock import patch

        from tickets.models import Mascara
        from tickets.services import notificar_mascaras_por_email

        Mascara.objects.create(
            nome="Reset",
            destino="GC",
            tipos=TipoDemanda.RESET_SENHA,
            template="TT {{tt}}",
            enviar_email=True,
            ativo=True,
        )
        ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.PRIORIDADE_ELITE, pedido="9"
        )
        with patch(
            "gestao.messaging.email_smtp.enviar_email_com_anexos",
            return_value=(True, ""),
        ) as send:
            n = notificar_mascaras_por_email(ticket)
        self.assertEqual(n, 0)
        send.assert_not_called()

