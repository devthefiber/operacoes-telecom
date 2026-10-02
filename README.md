# Operações Telecom

Sistema em desenvolvimento para gestão de operações de telecomunicações, construído com Django, PostgreSQL, Redis e Celery. Todo o ambiente de desenvolvimento é orquestrado utilizando Docker e Docker Compose.

## Tecnologias Utilizadas

- **Python 3.12** & **Django 5.0+**
- **PostgreSQL 15** (Banco de Dados)
- **Redis 7** (Message Broker / Cache)
- **Celery 5.4+** (Processamento de Tarefas Assíncronas)
- **Docker & Docker Compose**

## Pré-requisitos

Para rodar o projeto localmente, certifique-se de ter instalado em sua máquina:
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

*(Nota: Em ambientes LXC como o Proxmox, pode ser necessário realizar um downgrade da biblioteca `containerd` ou `runc` para evitar conflitos de permissões do AppArmor).*

## Como Configurar e Rodar o Ambiente Local

**1. Clone o repositório e acesse a pasta do projeto:**
```bash
# git clone <url-do-repositorio>
cd operacoes-telecom_dev
```

**2. Configure as variáveis de ambiente:**
Certifique-se de que o arquivo `.env` existe na raiz do projeto contendo as credenciais do banco e configurações do Django. Exemplo:
```env
DEBUG=True
SECRET_KEY='sua-chave-secreta'
DB_NAME=operacoes_telecom_db
DB_USER=operacoes_admin
DB_PASSWORD=sua_senha_segura
DB_HOST=db
DB_PORT=5432
```

**3. Suba os containers com o Docker Compose:**
O comando abaixo irá construir a imagem da aplicação e subir todos os serviços (Web, DB, Redis, Celery) em segundo plano:
```bash
docker compose up --build -d
```

**4. Aplique as migrações no banco de dados:**
Para criar as tabelas nativas do Django no PostgreSQL:
```bash
docker compose exec web python manage.py migrate
```

**5. Crie o seu usuário administrador (Opcional):**
```bash
docker compose exec web python manage.py createsuperuser
```

## Acesso à Aplicação

- **Interface Web do Django:** Acesse no seu navegador `http://localhost:8005/` (ou pelo IP do seu servidor).
- **Acesso Externo ao PostgreSQL:** O banco de dados está exposto na porta host `8003` para uso com ferramentas de gerenciamento (ex: DBeaver, pgAdmin).

## Dicas Úteis de Desenvolvimento

- Para parar e derrubar a infraestrutura atual:
  ```bash
  docker compose down
  ```
- Para ver os logs em tempo real da aplicação web:
  ```bash
  docker compose logs -f web
  ```
- Para acessar o shell interativo do Django dentro do container:
  ```bash
  docker compose exec web python manage.py shell
  ```
- Para reiniciar apenas os workers do Celery (útil ao mudar lógicas de background):
  ```bash
  docker compose restart celery
  ```
