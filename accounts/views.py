from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings

from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_operacoes')

    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        
        user = authenticate(request, username=u, password=p)
        if user is not None:
            auth_login(request, user)
            messages.success(request, f'Bem-vindo de volta, {user.username}!')
            
            # Se a flag de trocar senha estiver ativa, manda pra tela de forçar senha
            if hasattr(user, 'perfil') and user.perfil.deve_trocar_senha:
                return redirect('force_password_change')
                
            return redirect('dashboard_operacoes')
        else:
            messages.error(request, 'Usuário ou senha incorretos.')
            
    return render(request, 'accounts/login.html')

def logout_view(request):
    auth_logout(request)
    messages.success(request, 'Você saiu do sistema com sucesso.')
    return redirect('login')

def request_access_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        department = request.POST.get('department')
        
        subject = f'Nova Solicitação de Acesso - {name}'
        message = f"Nome: {name}\nE-mail: {email}\nSetor: {department}\n\nPor favor, crie o usuário no painel administrativo."
        
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            # Verificar se o e-mail já existe
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Este e-mail já possui um acesso ou solicitação no sistema.')
                return redirect('request_access')
                
            # Criar o usuário inativo e pendente
            # Usamos o email como username também
            novo_usuario = User.objects.create_user(
                username=email,
                email=email,
                first_name=name,
                is_active=False, # Não consegue logar ainda
            )
            novo_usuario.set_unusable_password()
            novo_usuario.save()
            
            # O sinal já criou o perfil, só atualizamos:
            novo_usuario.perfil.setor = department
            novo_usuario.perfil.status_solicitacao = 'PENDENTE'
            novo_usuario.perfil.save()
            
            # Pega e-mails de todos os usuários que têm permissão de admin (is_staff=True)
            admins = User.objects.filter(is_staff=True, is_active=True).exclude(email='')
            admin_emails = list(admins.values_list('email', flat=True))
            
            if admin_emails:
                from django.template.loader import render_to_string
                from django.utils.html import strip_tags
                
                html_message = render_to_string('accounts/request_access_email.html', {
                    'name': name,
                    'email': email,
                    'department': department,
                })
                plain_message = strip_tags(html_message)
                
                send_mail(
                    subject,
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    admin_emails,
                    html_message=html_message,
                    fail_silently=False,
                )
            else:
                print("Aviso: Nenhum administrador encontrado com e-mail cadastrado para receber a notificação.")
                
            messages.success(request, 'Solicitação enviada com sucesso! Seu cadastro está pendente de aprovação.')
            return redirect('login')
        except Exception as e:
            print(f"Erro ao solicitar acesso: {e}")
            messages.error(request, 'Ocorreu um erro ao processar sua solicitação.')
            return redirect('request_access')

    return render(request, 'accounts/request_access.html')

@login_required
def force_password_change_view(request):
    if not hasattr(request.user, 'perfil') or not request.user.perfil.deve_trocar_senha:
        return redirect('dashboard_operacoes')
        
    if request.method == 'POST':
        p1 = request.POST.get('new_password')
        p2 = request.POST.get('confirm_password')
        
        if p1 and p2 and p1 == p2:
            if len(p1) < 8:
                messages.warning(request, 'A senha deve ter pelo menos 8 caracteres.')
            else:
                user = request.user
                try:
                    from django.contrib.auth.password_validation import validate_password
                    validate_password(p1, user)
                except Exception:
                    pass
                user.set_password(p1)
                user.perfil.deve_trocar_senha = False
                user.perfil.save()
                user.save()
                
                # O Django desloga o usuário quando a senha muda, precisamos relogar ele
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, user)
                
                messages.success(request, 'Senha atualizada com sucesso! Bem-vindo ao painel.')
                return redirect('dashboard_operacoes')
        else:
            messages.error(request, 'As senhas não conferem.')
            
    return render(request, 'accounts/force_password_change.html')

from django.contrib.auth.views import PasswordResetConfirmView

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        if hasattr(user, 'perfil') and user.perfil.deve_trocar_senha:
            user.perfil.deve_trocar_senha = False
            user.perfil.save()
        return response
