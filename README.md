# XS Intelligence 1.0

Dashboard de vendas da XS. Não altera a planilha original e não apresenta nomes ou contatos de pacientes.

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Para testar sem credenciais, use a opção de upload de CSV/XLSX exportado da aba VENDAS. Os arquivos enviados são processados na sessão do app; evite hospedar publicamente enquanto houver dados internos.

## Conexão privada com Google Sheets

1. No Google Cloud, crie projeto e ative **Google Sheets API** e **Google Drive API**.
2. Crie uma conta de serviço e uma chave JSON; compartilhe a planilha original com o e-mail da conta de serviço como **Leitor**.
3. No Streamlit Community Cloud, em **App settings > Secrets**, insira:

```toml
spreadsheet_id = "1M-kJTc5QvA1OYXDtBe2ChK8iyLX_P0s7gs2TV-pRdzg"
[google_service_account]
type = "service_account"
project_id = "SEU_PROJETO"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

Copie os demais campos da chave JSON, respeitando a sintaxe TOML; nunca envie a chave para o chat nem coloque-a no GitHub. Pode usar a estrutura integral de credenciais em `google_service_account`.

## Publicação

Envie esta pasta para um repositório GitHub **privado**, conecte-o ao Streamlit Community Cloud e selecione `app.py`. Configure secrets no painel da hospedagem. Verifique as regras de visibilidade/controle de acesso do plano antes de compartilhar. A hospedagem gratuita pode não atender a um requisito de app privado; nesse caso use hospedagem com autenticação ou outra solução restrita.

## Métricas

- `VENDAS` com `Status = FECHADO`, data válida e valor monetário convertido.
- Faturamento: soma de Valor; vendas: contagem de linhas; ticket médio: faturamento / vendas.
- `Indicação` = pessoa que originou; `REF. INDICAÇÃO` = canal de origem; `Fisioterapeuta` = quem fechou.
- Comparações de meses parciais são explicitamente identificadas.
- Datas inválidas, como anos `0206`, são descartadas e contabilizadas no aviso de qualidade.
- A classificação de reabilitação/recovery depende do texto da coluna `Serviço`.
- A seção de leads e atendimentos será incluída depois de validação das respectivas abas.
