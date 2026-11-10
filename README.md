# Operações Telecom — Painel de Gestão e Performance Operacional

Sistema web corporativo para gestão, acompanhamento diário e apuração de produtividade técnica e qualidade das operações de campo da **The Fiber** (setores de **Ativação** e **Manutenção**).

> **Aviso para novos mantenedores**: Este manual foi escrito para que qualquer pessoa consiga operar, manter e atualizar este projeto no servidor, **mesmo que possua pouco ou nenhum conhecimento prévio em Django ou Python**.

---

## Sumário
1. [Visão Geral e Objetivos do Sistema](#1-visão-geral-e-objetivos-do-sistema)
2. [Dicionário para Quem Não Conhece Django](#2-dicionário-para-quem-não-conhece-django)
3. [Arquitetura e Contêineres (Docker)](#3-arquitetura-e-contêineres-docker)
4. [Estrutura do Servidor (DEV vs PROD)](#4-estrutura-do-servidor-dev-vs-prod)
5. [Como o Sistema Atualiza os Dados Automaticamente](#5-como-o-sistema-atualiza-os-dados-automaticamente)
6. [Módulos e Regras de Negócio do Sistema](#6-módulos-e-regras-de-negócio-do-sistema)
7. [Guia de Comandos e Operação Diária](#7-guia-de-comandos-e-operação-diária)
8. [Passo a Passo para Atualizar o Código (Deploy)](#8-passo-a-passo-para-atualizar-o-código-deploy)
9. [Solução de Problemas Comuns (Troubleshooting)](#9-solução-de-problemas-comuns-troubleshooting)

---

## 1. Visão Geral e Objetivos do Sistema

O **Operações Telecom** substitui planilhas manuais e unifica as fontes de dados de Ordens de Serviço (OS) do IXC Soft e do Data Warehouse (DW do Airflow).

### Principais Funcionalidades:
- **Painel Operacional com Visão Diária e Mensal**: Acompanhamento de metas de volume, retrabalho, garantia de 30 dias e auditorias técnicas.
- **Tabela de Manutenção e Tabela de Ativação**: Cálculo automatizado por técnico e supervisor, com notas finais ponderadas.
- **Indicador Executivo TT BASE (%)**: Taxa percentual de chamados de suporte técnico em relação à carteira total de clientes ativos.
- **Configuração Dinâmica de Equipes**: Gestão mensal de colaboradores, supervisores, setores e tipos de contratação (`CLT`, `PJ`, `(Prev.)`, `(Ap)` e `N/C`).
- **De-Para de Assuntos de OS**: Interface autônoma para os gestores escolherem quais motivos contam como *Garantia 30D* ou *Suporte*.
- **Gestão de Expurgos**: Possibilidade de expurgar (desconsiderar) OSs indevidas com registro de auditoria e justificativa.
- **Calendário Dinâmico de Dias Úteis**: Considera dias úteis com pesos (Seg–Sex: 1.0, Sáb: 0.5, Dom/Feriados: 0.0) integrado aos feriados nacionais e estaduais.

---

## 2. Dicionário para Quem Não Conhece Django

Se você está assumindo o projeto agora e nunca mexeu com Django, aqui está o resumo do que cada arquivo faz:

| Arquivo / Pasta | O que é? | Função na prática |
| :--- | :--- | :--- |
| `operacoes/models.py` | **Modelos de Dados** | Define como são as tabelas no PostgreSQL (colunas, tipos e relacionamentos). Se você mudar algo aqui, precisará criar uma *migration*. |
| `operacoes/views.py` | **Controladores / Views** | É o cérebro das páginas. Faz as contas, busca os dados no banco e envia o resultado pronto para as telas. |
| `operacoes/utils.py` | **Funções Auxiliares** | Onde ficam os cálculos reutilizáveis: contagem de dias úteis, cálculo do TT Base, replicação automática de meses e sincronização de assuntos. |
| `operacoes/urls.py` | **Rotas (URLs)** | Associa cada endereço do navegador a uma função em `views.py` (ex: `/configuracoes/assuntos/`). |
| `operacoes/templates/` | **Telas Visuais (HTML)** | Os arquivos que compõem a interface visual acessada pelos usuários. Contêm HTML, CSS e JavaScript. |
| `operacoes/tasks.py` | **Tarefas Celery (Background)** | Tarefas automáticas que rodam em segundo plano (como a importação da madrugada). |
| `operacoes/migrations/` | **Histórico do Banco** | Arquivos automáticos que ensinam o PostgreSQL a criar ou alterar tabelas quando o `models.py` é alterado. |
| `operacoes/admin.py` | **Painel Admin** | Configura o que aparece no painel padrão do Django (`http://.../admin/`). |
| `core_project/` | **Configurações Centrais** | Guarda as chaves do projeto, conexões de banco de dados (`settings.py`) e agendador de tarefas (`celery.py`). |

---

## 3. Arquitetura e Contêineres (Docker)

O projeto roda inteiramente dentro de contêineres Docker gerenciados pelo `docker compose`:

```
+-----------------------------------------------------------------------------------+
| SERVIDOR THE FIBER                                                                |
|                                                                                   |
|   +-----------------------+     Porta 8006 (Prod)     +-----------------------+   |
|   |   Navegador / Usuário | ----------------------->  |  web (Django/Gunicorn)|   |
|   +-----------------------+                           +-----------+-----------+   |
|                                                                   |               |
|                                                                   v               |
|   +-----------------------+                           +-----------+-----------+   |
|   |  redis:7 (Fila)       | <------------------------ |  db:15 (PostgreSQL)   |   |
|   +-----------+-----------+                           +-----------------------+   |
|               |                                                                   |
|       +-------+-------+                                                           |
|       |               |                                                           |
|       v               v                                                           |
|   +-------+       +---------------+                                               |
|   | celery|       |  celery-beat  |                                               |
|   | worker|       | (Agendador 3h)|                                               |
|   +-------+       +---------------+                                               |
+-----------------------------------------------------------------------------------+
```

### Serviços do Docker:
1. **`web`**: A aplicação Django servida via Gunicorn.
2. **`db`**: Banco de dados PostgreSQL 15 oficial do sistema.
3. **`redis`**: Banco em memória usado como fila para tarefas assíncronas.
4. **`celery`**: O trabalhador que executa a importação e o vínculo inteligente de OSs.
5. **`celery-beat`**: O despertador que dispara a tarefa toda madrugada às **03:30**.

---

## 4. Estrutura do Servidor (DEV vs PROD)

No servidor do projeto existem dois diretórios principais:

| Ambiente | Diretório no Servidor | Porta Web | Porta DB Externa | Finalidade |
| :--- | :--- | :---: | :---: | :--- |
| **Desenvolvimento (DEV)** | `/home/desenv/projetos/operacoes-telecom_dev` | `8005` | `5434` | Onde você altera e testa o código antes de subir. |
| **Produção (PROD)** | `/home/desenv/projetos/operacoes-telecom` | `8006` | `5433` | O sistema oficial utilizado pelos usuários da empresa. |

> **IMPORTANTE**: Nunca edite arquivos diretamente na pasta de produção sem commitar e testar antes na pasta `operacoes-telecom_dev`.

---

## 5. Como o Sistema Atualiza os Dados Automaticamente

O fluxo de dados diário ocorre de forma automática todas as noites:

1. **03:00**: A DAG do **Airflow** extrai as Ordens de Serviço do IXC Soft e grava na tabela `relatorio_os_setembro` do Data Warehouse (DW).
2. **03:30**: O serviço `celery-beat` acorda e dispara a tarefa `sincronizar_dados_do_airflow` (`operacoes/tasks.py`):
   - **Passo 1 (`importar_os_airflow`)**: Lê as novas OSs do DW e salva no PostgreSQL local (`operacoes_telecom_db`).
   - **Passo 2 (`vincular_os`)**: Algoritmo inteligente que analisa OSs filhas de Auditoria, Retrabalho e Reincidência e as conecta à OS de instalação/reparo original do cliente.
   - **Passo 3 (`garantir_alocacao_mes`)**: Se tiver virado o mês (ex: entrou dia 1º de um novo mês), clona automaticamente a alocação de técnicos e metas do mês anterior para o painel não ficar vazio.
   - **Passo 4 (`sincronizar_assuntos_disponiveis`)**: Varre as novas OSs e insere novos motivos automaticamente na tela de De-Para.

### Como forçar a atualização imediata via comando:
Se o gestor pedir para atualizar os dados durante o dia sem esperar a madrugada:
```bash
# No diretório de produção:
cd /home/desenv/projetos/operacoes-telecom
docker exec operacoes-telecom-web-1 python manage.py importar_os_airflow
docker exec operacoes-telecom-web-1 python manage.py vincular_os
```

---

## 6. Módulos e Regras de Negócio do Sistema

### 6.1. Dashboard Principal (`/`)
- **Seletor de Período**: Permite navegar entre qualquer mês e ano histórico.
- **Cartões de Resumo (Topo)**:
  - **Dias Úteis (Mês)**: Total de dias úteis projetados para o mês (Seg–Sex = 1, Sáb = 0.5, Dom/Feriado = 0).
  - **Dias Trabalhados**: Dias úteis decorridos até D-1.
  - **Dias Faltantes**: Dias restantes para o fechamento do mês.
  - **TT BASE**: Percentual projetado de chamados de suporte sobre a base de clientes do mês:
    $$\text{TT Base (\%)} = \frac{\left(\frac{\text{Volume Suporte}}{\text{Dias Trabalhados}} \times \text{Dias Úteis Totais}\right)}{\text{Base de Clientes}} \times 100$$
    *(Quando o mês fecha, o cálculo utiliza diretamente `Volume Suporte / Base de Clientes`)*.
- **Tabela de Manutenção**:
  - Exibe técnicos alocados no setor de Manutenção.
  - Colunas de Volume (Suporte, Serviços, Total), Retrabalho, Garantia 30D, Auditoria de Qualidade, Field Audit e Nota Final.
  - *Nota*: As colunas `% Ating.` de retrabalho e `Resultado Técnico` foram ocultadas visualmente a pedido da coordenação para otimizar espaço de tela em monitores 1366px e 1080p, mantendo o cálculo intacto na nota final.
- **Tabela de Ativação**:
  - Exibe técnicos do setor de Ativação, volumes de instalações, reincidências de suporte entre 16 e 30 dias após ativação, e aprovações de auditoria.

### 6.2. Configurações da Equipe (`/configuracoes/`)
- Define para cada mês: Técnico, Cargo, Supervisor responsável, Setor (Ativação ou Manutenção) e Tipo de Contratação (`CLT` ou `PJ`).
- **Marcações Especiais ao lado do nome do técnico**:
  - `(Prev.)`: Técnico focado em Preventiva.
  - `(Ap)`: Aprendiz / Em treinamento.
  - `(PJ)`: Prestador de serviço terceirizado.
- **Flag `Contabiliza Indicadores`**: Quando desmarcada, o técnico não pontua na meta geral da equipe e exibe o badge discreto cinza `N/C` (Não Contabiliza) ao lado do nome.
- **Replicação Automática**: Ao virar o mês, o sistema cria o mês seguinte sozinho copiando toda a equipe do mês anterior.

### 6.3. Base de Clientes - TT Base (`/configuracoes/base-cliente/`)
- Tela acessível pelo Menu Hambúrguer.
- Lista os 12 meses do ano e permite digitar o número de clientes ativos (ex: `31836` em Outubro).
- Possui botão **✏️ Editar** para atualizar o valor instantaneamente.

### 6.4. De-Para de Assuntos de OS (`/configuracoes/assuntos/`)
- Dá autonomia total ao administrador para decidir quais assuntos de OS contam como:
  - **Garantia 30D (Manutenção)**
  - **Suporte / Reincidência (Ativação)**
  - **Outros / Desconsiderar**
- Possui busca em tempo real, filtros por categoria e chavinha liga/desliga com salvamento automático via AJAX.

### 6.5. Metas Operacionais (`/configuracoes/metas/`)
- Histórico de metas de volume diário, tolerância de retrabalho, meta de garantia e auditorias mínimas.

### 6.6. Gestão de Expurgos (`/expurgos/`)
- Permite pesquisar qualquer OS pelo ID IXC e expurgá-la dos cálculos operacionais com justificativa obrigatória.

---

## 7. Guia de Comandos e Operação Diária

Todos os comandos abaixo devem ser executados no terminal Linux do servidor:

### 7.1. Ver o status dos contêineres:
```bash
docker ps
```
Você verá os contêineres:
- `operacoes-telecom-web-1`
- `operacoes-telecom-db-1`
- `operacoes-telecom-redis-1`
- `operacoes-telecom-celery-1`
- `operacoes-telecom-celery-beat-1`

### 7.2. Ver os logs da aplicação em tempo real:
```bash
docker logs -f operacoes-telecom-web-1
```
*(Pressione `Ctrl + C` para sair dos logs).*

### 7.3. Reiniciar a aplicação (se o sistema ficar lento ou travado):
```bash
docker restart operacoes-telecom-web-1 operacoes-telecom-celery-1 operacoes-telecom-celery-beat-1
```

### 7.4. Criar um novo usuário administrador:
```bash
docker exec -it operacoes-telecom-web-1 python manage.py createsuperuser
```

### 7.5. Trocar a senha de um usuário existente:
```bash
docker exec -it operacoes-telecom-web-1 python manage.py changepassword <nome_do_usuario>
```

### 7.6. Abrir o console interativo do Django (Shell):
```bash
docker exec -it operacoes-telecom-web-1 python manage.py shell
```

---

## 8. Passo a Passo para Atualizar o Código (Deploy)

Sempre que você ou outro desenvolvedor fizer alterações no código, siga rigorosamente esta sequência de comandos:

### 1º Passo: Testar e commitar na pasta DEV:
```bash
cd /home/desenv/projetos/operacoes-telecom_dev

# Verifique quais arquivos foram modificados
git status

# Adicione os arquivos e crie o commit
git add .
git commit -m "descricao clara da mudanca realizada"

# Envie as alterações para o repositório remoto (GitHub)
git push origin main
```

### 2º Passo: Atualizar a Produção (PROD):
```bash
cd /home/desenv/projetos/operacoes-telecom

# Baixe as alterações do GitHub
git pull origin main

# Aplique alterações no banco de dados (se houver migrations novas)
docker exec operacoes-telecom-web-1 python manage.py migrate

# Reinicie os serviços para carregar o novo código Python
docker restart operacoes-telecom-web-1 operacoes-telecom-celery-1 operacoes-telecom-celery-beat-1
```

### 3º Passo: Validar:
Abra o navegador no endereço de produção `http://<IP-DO-SERVIDOR>:8006/` e confirme se a aplicação responde normalmente.

---

## 9. Solução de Problemas Comuns (Troubleshooting)

### ❓ "A página está em branco ou deu erro 500"
1. Veja o que causou o erro no log do contêiner:
   ```bash
   docker logs --tail 100 operacoes-telecom-web-1
   ```
2. Na maioria das vezes, o erro é uma migração que faltou rodar:
   ```bash
   docker exec operacoes-telecom-web-1 python manage.py migrate
   docker restart operacoes-telecom-web-1
   ```

### ❓ "Os dados do dashboard estão desatualizados"
1. Verifique se a rotina noturna do Celery rodou:
   ```bash
   docker logs --tail 100 operacoes-telecom-celery-1
   ```
2. Force a execução manual dos comandos:
   ```bash
   docker exec operacoes-telecom-web-1 python manage.py importar_os_airflow
   docker exec operacoes-telecom-web-1 python manage.py vincular_os
   ```

### ❓ "O banco de dados não está respondendo (Connection refused)"
Verifique se o contêiner do PostgreSQL está ativo:
```bash
docker ps | grep operacoes-telecom-db
```
Se não estiver listado, suba os contêineres:
```bash
cd /home/desenv/projetos/operacoes-telecom
docker compose up -d
```

---

## Contatos e Suporte
- **Equipe de Desenvolvimento The Fiber**
- **Repositório Oficial**: `https://github.com/devthefiber/operacoes-telecom.git`
