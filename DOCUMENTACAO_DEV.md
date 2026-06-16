# 📖 Documentação do Desenvolvedor (Guia Técnico)

Este documento detalha o funcionamento interno, a arquitetura, a configuração de ambiente e as regras de negócio aplicadas no sistema **Emissor de NFS-e Nacional**.

---

## 🏗️ 1. Arquitetura e Tecnologias

O sistema utiliza uma arquitetura baseada em microsserviços desacoplados (Frontend SPA + Backend REST API), desenhada para alta concorrência e processamento assíncrono.

### Stack Tecnológica (Backend - Python 3.12+)

* **FastAPI:** Framework assíncrono para roteamento da API REST.
* **MongoDB (PyMongo):** Banco de dados NoSQL. Ideal para flexibilidade de payloads variáveis.
* **APScheduler:** Gerenciador de tarefas em background (Workers).
* **lxml & xml.etree:** Parsing, manipulação e canonicalização (c14n) de XML.
* **cryptography & requests_pkcs12:** Extração de chaves RSA de certificados `.pfx` e requisições via mTLS.
* **pdfplumber:** Extração de dados textuais e tabelas do PGDAS-D.
* **openpyxl:** Geração e leitura de relatórios e planilhas em lote.

### Stack Tecnológica (Frontend - React 18)

* **Vite:** Bundler ultrarrápido para ambiente de desenvolvimento e build.
* **React Router DOM:** Controle de navegação e proteção de rotas privadas.
* **Axios:** Cliente HTTP configurado com *interceptors* para injeção automática de JWT.
* **Lucide React:** Biblioteca de ícones SVG.

---

## ⚙️ 2. Configuração do Ambiente Local (Setup)

### Passo 2.1: Banco de Dados

Certifique-se de ter o MongoDB rodando localmente na porta padrão ou possua uma URI válida do MongoDB Atlas.

* URI Padrão: `mongodb://localhost:27017`
* Database gerado automaticamente: `nfse_db`

### Passo 2.2: Backend

1. Acesse o diretório do backend e crie o ambiente virtual:
```bash
python -m venv .venv

```


2. Ative o ambiente virtual:
* Windows: `.venv\Scripts\activate`
* Linux/Mac: `source .venv/bin/activate`


3. Instale as dependências:
```bash
pip install -r requirements.txt

```


4. Crie o arquivo `.env` na raiz do backend:
```env
SECRET_KEY=sua_chave_jwt_aqui_bem_longa
ENCRYPTION_KEY=sua_chave_fernet_base64_aqui=
MONGO_URI=mongodb://localhost:27017
AMBIENTE_NFSE=2 # 1=Produção, 2=Homologação
URL_API_NACIONAL=https://sefin.nfse.gov.br/SefinNacional/nfse
URL_DANFSE=https://adn.nfse.gov.br/danfse
EMAIL_ADDRESS=seu_email@gmail.com
EMAIL_PASSWORD=sua_senha_de_app_do_google
FRONTEND_URL=http://localhost:5173

```


5. Inicie a API:
```bash
uvicorn main:app --host 0.0.0.0 --port 6600 --reload --reload-excludes "logs/*" "*.log"

```



### Passo 2.3: Frontend

1. Acesse a pasta `frontend/`.
2. Instale os pacotes:
```bash
npm install

```


3. Crie o arquivo `.env` na pasta `frontend/`:
```env
VITE_API_URL=http://localhost:6600

```


4. Inicie o servidor de desenvolvimento:
```bash
npm run dev

```



---

## 🗄️ 3. Estrutura do Banco de Dados (Collections)

O banco de dados `nfse_db` opera com as seguintes coleções principais:

| Collection | Propósito |
| --- | --- |
| `users` | Armazena dados de autenticação, e-mail e hash da senha (`bcrypt`). |
| `emitters` | Dados cadastrais, fiscais e caminhos para os certificados `.pfx` no servidor. |
| `clients` | Carteira de clientes. Possui flags como `atualizado_recente` geradas pelo worker do ReceitaWS. |
| `aliquotas` | Histórico mensal de RBT12, RPA e alíquota efetiva. Contém a origem do dado (PDF ou Sistema). |
| `tasks_draft` | Fila temporária para validação de planilhas. Controla agrupamento de duplicadas (`duplicate_group_id`). |
| `tasks` | A fila oficial de processamento. Possui máquina de estados rígida (Status: *pending, retry_dps, accepted, error, canceled*). |

---

## 🚀 4. Máquina de Estados e Workers (APScheduler)

O sistema foi desenhado para **não bloquear a thread principal** da API durante a comunicação com a Receita. Tudo ocorre em *Background Workers* no arquivo `main.py`.

### Fluxo de Transmissão (NFSe)

1. **Geração:** O endpoint `/notas/confirmar` valida a requisição, assina o XML e salva na collection `tasks` com status `pending`. O frontend é liberado instantaneamente.
2. **Job 1 - Transmissão (`process_pending_nfse` - a cada 15s):**
* Busca até 5 tasks `pending`.
* Compacta o XML assinado em GZIP e encoda em Base64.
* Envia via mTLS (`requests_pkcs12`).
* Se a conexão cair (`RemoteDisconnected`), incrementa o `retry_count` e mantém `pending` até o limite de 5 tentativas.
* Se a API da Receita retornar erro `E999` ou de duplicidade de DPS, o status vai para `retry_dps`.
* Se for aceita, status atualiza para `accepted`.


3. **Job 2 - Auto-Correção (`process_retry_dps` - a cada 20s):**
* Pega notas que falharam por duplicidade de sequência (DPS).
* Remove a assinatura XML anterior, consome um novo número de DPS via `next_dps()`, reassina o XML e devolve para `pending`.


4. **Job 3 - Download de DANFS-e (`tarefa_recuperar_pdfs_pendentes` - a cada 2 min):**
* Busca tasks `accepted` cujo `pdf_base64` seja nulo.
* Faz o *HTTP GET* no portal oficial usando a Chave de Acesso e anexa o binário do PDF ao documento da task.



### Workers Cadastrais e Fiscais

* **Job 4 - Manutenção Cadastral (`atualizar_dados_clientes` - Diário à 01h00):**
* Varre os clientes cujo `updated_at` tem mais de 30 dias.
* Realiza um GET na API da ReceitaWS respeitando o *Rate Limit* (intervalos de 21 segundos).
* Atualiza os campos (endereço, razão social) silenciosamente no banco.


* **Job 5 - Recálculo Fiscal (`tarefa_recalcular_aliquotas_mensais` - Dia 1º de cada mês às 08h00):**
* Garante que nenhum emissor fique sem alíquota se o contador esquecer de fazer o upload do PDF. Reúne o histórico e o faturamento dentro da própria plataforma.



---

## 🧮 5. Motor de Cálculo Fiscal (Simples Nacional)

A lógica fiscal está concentrada no arquivo `aliquota.py` e no construtor `nfse_builder.py`.

* **Restrição Importante:** A tabela *hardcoded* (`TABELA_ANEXO_III`) e a partição fixa do ISS em **33,50%** garantem precisão exclusivamente para prestadores do **Anexo III**.
* **Parsing de PDF (`pdfplumber`):** A função de extração localiza a string âncora *"Período de Apuração"*, lê as tabelas de faturamento dos últimos 12 meses e recalcula a efetividade:
* `V1` = RBT12.
* `V2` = V1 * Alíquota Nominal.
* `V3` = V2 - Parcela a Deduzir.
* `Alíquota Efetiva` = V3 / V1.


* **XML Builder:** O sistema calcula a fração do ISS sobre a alíquota efetiva e aplica a Trava Constitucional (limite de 5% municipal) antes de preencher a tag `<pAliq>`.

---

## 🔐 6. Segurança e Criptografia

1. **Manejo de Certificados (`.pfx`):**
* Os arquivos não são persistidos no banco de dados. Ficam salvos na pasta `/uploads/certificados/`.
* Esta pasta **deve ser ignorada pelo Git** (`.gitignore`) e mantida apenas na máquina host da aplicação.


2. **Assinatura XML (DSIG):**
* A lógica implementada (`signer.py`) atende o padrão da SEFIN. O arquivo localiza o ID da tag (ex: `<infDPS Id="DPS1234...">`), canonicaliza o fragmento isolado usando o método `c14n` exclusívo e gera o `DigestValue` (SHA1).
* Em seguida, assina digitalmente o `SignedInfo` injetando a chave privada RSA do emissor.


3. **Variáveis Globais:**
* Chaves de criptografia e SMTP trafegam estritamente pelo arquivo `.env`.



---

## 🛠️ 7. Extensibilidade Futura

Ao dar manutenção ou escalar o sistema, observe:

* **Novos Anexos (I, II, IV, V):** Exigirá a parametrização de novas tabelas em `aliquota.py` e a flexibilização do fator de repartição do ISS no XML.
* **Deploy (Nuvem):** Recomenda-se utilizar Docker (contêineres separados para Frontend e Backend) ou um Proxy Reverso (NGINX/Caddy) apontando para a porta do Uvicorn (6600). Certifique-se de configurar certificados SSL/HTTPS no servidor final.