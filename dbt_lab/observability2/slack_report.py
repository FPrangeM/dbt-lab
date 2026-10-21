import json
import pandas as pd
import duckdb
import os
from dotenv import load_dotenv
from tabulate import tabulate
import requests # Necessário para o envio do webhook
from datetime import datetime, timezone # Necessário para a data

arquivo_env = '/home/prange/Documentos/repos/dbt-lab/.env'
load_dotenv(arquivo_env) 

webhook = os.environ.get("SLACK_WEBHOOK_URL")
db_path = os.environ.get("DQ_DB_PATH")
db_path = '/home/prange/Documentos/repos/dbt-lab/db/my-duckdb.duckdb'

# ====================================================================
base = 'Base RH'

# Dicionário de textos original mantido, mas não será o foco principal 
# já que vamos construir blocos customizados.
TEXTO = {
    "sucesso": (
        "🟢 Qualidade dos Dados | {base}",
        "✨ **Base validada com sucesso**",
        "> Todas as regras de qualidade foram atendidas. Os dados estão prontos para consumo.",
    ),
    "problemas": (
        "🟠 Qualidade dos Dados | {base}",
        "🔎 **Encontramos pontos que precisam de atenção**",
        "> A atualização foi processada, mas alguns registros não atenderam às regras de qualidade.",
    )
}

# ====================================================================
# Verificar os resultados dos testes

with open('/home/prange/Documentos/repos/dbt-lab/dbt_lab/target/run_results.json', 'r') as arquivo:
    run_results = json.load(arquivo)

df_status = pd.DataFrame(run_results['results'])
df_status = df_status[['unique_id', 'status']]

with open('/home/prange/Documentos/repos/dbt-lab/dbt_lab/target/manifest.json', 'r') as arquivo:
    manifest = json.load(arquivo)

df_modelos = pd.DataFrame(manifest['nodes'].values())
# df_modelos = df_modelos[['unique_id', 'tags', 'meta']]
df_modelos = df_modelos[['unique_id', 'tags', 'meta', 'relation_name']]


df_modelos = df_modelos[df_modelos['tags'].apply(lambda tags: 'rh' in tags)]

df_meta = pd.json_normalize(df_modelos['meta'], sep='_')
df_modelos = pd.concat(
    [df_modelos.drop(columns='meta').reset_index(drop=True),
     df_meta.reset_index(drop=True)],
    axis=1
)

df_geral = pd.merge(df_modelos, df_status, on='unique_id', how='left')
df_geral = df_geral[df_geral['status'] == 'warn']

# ====================================================================
# Construção da mensagem no Slack

# Inicializa a lista de blocos do Slack
slack_blocks = []

# Cabeçalho (Contexto e Título)
agora = datetime.now()
data_formatada = agora.strftime('%d/%m/%Y %H:%M')

slack_blocks.append({
    "type": "context",
    "elements": [
        {
            "type": "mrkdwn",
            "text": "_Relatório automático de qualidade de dados_"
        }
    ]
})

slack_blocks.append({
    "type": "header",
    "text": {
        "type": "plain_text",
        "text": f"🟠 Qualidade dos Dados | {base}",
        "emoji": True
    }
})

slack_blocks.append({
    "type": "context",
    "elements": [
        {
            "type": "mrkdwn",
            "text": f"_Atualização · {data_formatada}_"
        }
    ]
})

slack_blocks.append({"type": "divider"})

# Contadores
qtd_problemas = len(df_geral)
# Exemplo de contador fixo total, você pode calcular isso baseado no seu manifest se preferir
qtd_total_controles = 3 
qtd_aprovados = qtd_total_controles - qtd_problemas

slack_blocks.append({
    "type": "section",
    "text": {
        "type": "mrkdwn",
        "text": f"🟠 *{qtd_problemas} ponto(s) de atenção* · {qtd_aprovados} de {qtd_total_controles} controles aprovados"
    }
})

slack_blocks.append({"type": "divider"})

slack_blocks.append({
    "type": "section",
    "text": {
        "type": "mrkdwn",
        "text": "🔎 *O que precisa ser corrigido*"
    }
})

# ====================================================================
# Extrair os itens do Audit e montar os blocos

with duckdb.connect(db_path) as conn:

    for unique_id in df_geral['unique_id']:
        model_info = df_geral[df_geral['unique_id'] == unique_id]

        audit_table = model_info['relation_name'].iloc[0]
        sample_columns = model_info['sample_columns'].iloc[0]
        
        # Título do teste obtido do metadata
        audit_title = model_info['title'].iloc[0] 

        querystr = f"""
        select 
            {", ".join(sample_columns)}
        from 
            {audit_table}
        """
        result_df = conn.query(querystr).df()

        # Mascaramento de CPF (ajustado para evitar erro caso a coluna não exista em algum teste)
        if 'CPF' in result_df.columns:
            result_df['CPF'] = (
                '***.***.' 
                + result_df['CPF'].astype(str).str[8:11] 
                + '-**'
            )

        result_df = result_df.astype(str).fillna("-")

        # Gerando a tabela em texto puro formatada
        tabela_txt = tabulate(
            result_df, 
            headers='keys', 
            tablefmt='simple', 
            showindex=False, 
            disable_numparse=True
        )

        # Adiciona o título do teste no Slack
        slack_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🔴 *{audit_title}*"
            }
        })

        slack_blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "*Registros*"
                }
            ]
        })

        # Adiciona a tabela em bloco de código (O Slack renderiza igual à imagem)
        slack_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```\n{tabela_txt}\n```"
            }
        })
        
        slack_blocks.append({"type": "divider"})

    # Adiciona texto final
    slack_blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "_Relatório automático de qualidade de dados_"
            }
        ]
    })

# ====================================================================
# Enviar para o Slack

payload = {"blocks": slack_blocks}

if webhook:
    response = requests.post(
        webhook, 
        data=json.dumps(payload),
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code == 200:
        print("Mensagem enviada com sucesso para o Slack!")
    else:
        print(f"Erro ao enviar para o Slack. Status: {response.status_code}, Resposta: {response.text}")
else:
    print("Webhook do Slack não configurado no .env")