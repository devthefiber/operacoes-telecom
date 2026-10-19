from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout, get_user_model
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.conf import settings
import jwt

def csrf_failure(request, reason=""):
    """
    Tratamento amigável para CSRF:
    Redireciona para o painel se já autenticado ou para o Hub central se não.
    """
    if request.user.is_authenticated:
        return redirect('dashboard_operacoes')
    return redirect(getattr(settings, 'PORTAL_HUB_URL', 'https://devsistema.thefiber.com.br/portal.html#operacoes'))

@csrf_exempt
def login_portal_view(request):
    """
    Única porta de entrada de autenticação do sistema.
    Recebe um POST cross-origin com o campo 'token' (JWT HS256) enviado pelo Hub The Fiber,
    valida a chave e a expiração, sincroniza o CustomUser local e o perfil (Admin vs Visitante),
    inicia a sessão Django e redireciona direto para o Dashboard.
    """
    hub_url = getattr(settings, 'PORTAL_HUB_URL', 'https://devsistema.thefiber.com.br/portal.html#operacoes')

    if request.method != 'POST':
        return redirect(hub_url)
        
    token = request.POST.get('token')
    if not token:
        messages.error(request, 'Token de autenticação não fornecido pelo Hub.')
        return redirect(hub_url)

    try:
        # 1. Validação do JWT com a chave compartilhada da empresa
        payload = jwt.decode(
            token,
            settings.PORTAL_JWT_SECRET,
            algorithms=["HS256"]
        )

        # 2. Validação do slug do módulo (aceita tanto operacoes quanto operacao)
        token_slug = payload.get("setor")
        valid_slugs = [settings.PORTAL_SLUG, "operacoes", "operacao"]
        if token_slug not in valid_slugs:
            messages.error(request, f"Token não destinado a este módulo (esperado: '{settings.PORTAL_SLUG}', recebido: '{token_slug}').")
            return redirect(hub_url)

        username = payload.get("sub")
        if not username:
            messages.error(request, 'Token inválido: identificador de usuário (sub) ausente.')
            return redirect(hub_url)

        nivel = payload.get("nivel", "visitante")
        is_admin = (nivel == "admin")

        # 3. Localização ou Criação do Usuário Local
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'first_name': username.split('.')[0].capitalize() if '.' in username else username.capitalize(),
                'email': f"{username}@thefiber.com.br" if '@' not in username else username,
                'is_staff': is_admin,
                'is_superuser': is_admin,
                'is_active': True,
            }
        )

        # 4. Sincronização do Nível de Permissão e Perfil
        fields_to_update = []
        if user.is_superuser:
            if not user.is_staff:
                user.is_staff = True
                fields_to_update.append('is_staff')
        else:
            if user.is_staff != is_admin:
                user.is_staff = is_admin
                fields_to_update.append('is_staff')
            if user.is_superuser != is_admin:
                user.is_superuser = is_admin
                fields_to_update.append('is_superuser')

        if not user.is_active:
            user.is_active = True
            fields_to_update.append('is_active')

        if fields_to_update:
            user.save(update_fields=fields_to_update)


        # Garantir que o perfil esteja aprovado e sem exigência de troca de senha local
        if hasattr(user, 'perfil'):
            perfil = user.perfil
            perfil_updated = False
            if perfil.status_solicitacao != 'APROVADO':
                perfil.status_solicitacao = 'APROVADO'
                perfil_updated = True
            if perfil.deve_trocar_senha:
                perfil.deve_trocar_senha = False
                perfil_updated = True
            if perfil_updated:
                perfil.save()

        # 5. Início de Sessão Django
        auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f"Autenticado com sucesso via Hub! Olá, {user.first_name or user.username}.")
        return redirect('dashboard_operacoes')

    except jwt.ExpiredSignatureError:
        messages.error(request, 'O token de acesso expirou. Clique novamente no card do Painel no Hub.')
        return redirect(hub_url)
    except jwt.InvalidTokenError:
        messages.error(request, 'Assinatura do token inválida. Verifique a chave de integração.')
        return redirect(hub_url)
    except Exception as e:
        messages.error(request, f'Erro inesperado na autenticação via Hub: {str(e)}')
        return redirect(hub_url)

@never_cache
def login_view(request):
    """
    Ponto de interceptação para usuários não autenticados.
    Como a autenticação é 100% via Hub, redireciona automaticamente para o Hub.
    """
    if request.user.is_authenticated:
        return redirect('dashboard_operacoes')
    hub_url = getattr(settings, 'PORTAL_HUB_URL', 'https://devsistema.thefiber.com.br/portal.html#operacoes')
    return redirect(hub_url)

def logout_view(request):
    """
    Encerra a sessão local no Dashboard e devolve o usuário direto ao Hub.
    """
    auth_logout(request)
    hub_url = getattr(settings, 'PORTAL_HUB_URL', 'https://devsistema.thefiber.com.br/portal.html#operacoes')
    return redirect(hub_url)
