from django.conf import settings

def portal_context(request):
    return {
        'PORTAL_HUB_URL': getattr(settings, 'PORTAL_HUB_URL', 'https://devsistema.thefiber.com.br/portal.html#operacoes'),
        'PORTAL_SLUG': getattr(settings, 'PORTAL_SLUG', 'operacoes'),
    }

