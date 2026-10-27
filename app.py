import io
import re
import unicodedata
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title='XS Intelligence 2.7', page_icon='📊', layout='wide')
SPREADSHEET_ID = '1M-kJTc5QvA1OYXDtBe2ChK8iyLX_P0s7gs2TV-pRdzg'
TEAM = ['Victor', 'Lucas Valentim', 'Lucas Marçal', 'Letícia']
GOALS = {'Lucas Marçal': 20750.0, 'Victor': 19400.0, 'Lucas Valentim': 12750.0, 'Letícia': 2100.0}
CLINIC_GOAL = 55000.0

def norm(value):
    text = str(value if pd.notna(value) else '').strip()
    return ''.join(c for c in unicodedata.normalize('NFD', text.upper()) if unicodedata.category(c) != 'Mn')

# Padronização dos nomes usados na aba VENDAS e no painel.
# A planilha utiliza frequentemente apenas o sobrenome dos profissionais.
ALIASES = {
    'VICTOR': 'Victor',
    'VICTOR MASCARENHAS': 'Victor',
    'MARCAL': 'Lucas Marçal',
    'LUCAS MARCAL': 'Lucas Marçal',
    'VALENTIM': 'Lucas Valentim',
    'LUCAS VALENTIM': 'Lucas Valentim',
    'LETICIA': 'Letícia',
}

def canonical_name(value):
    original = str(value if pd.notna(value) else '').strip()
    return ALIASES.get(norm(original), original)

def brl(value):
    return f'R$ {value:,.2f}'.replace(',', '#').replace('.', ',').replace('#', '.')

def parse_brl(value):
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r'[^0-9,.\-]', '', str(value))
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    elif text.count('.') > 1:
        text = text.replace('.', '')
    try:
        return float(text)
    except ValueError:
        return 0.0

@st.cache_data(ttl=300, show_spinner='Atualizando vendas...')
def get_sales(sheet_id, credentials):
    import gspread
    client = gspread.service_account_from_dict(credentials)
    values = client.open_by_key(sheet_id).worksheet('VENDAS').get_all_values()
    return pd.DataFrame(values[1:], columns=[str(h).strip() for h in values[0]]) if values else pd.DataFrame()

def prepare(raw):
    df = raw.copy()
    df.columns = [str(col).strip() for col in df.columns]
    required = {'DATA', 'Status', 'Valor', 'Fisioterapeuta', 'Serviço', 'Indicação', 'REF. INDICAÇÃO'}
    if required - set(df.columns):
        raise ValueError('Colunas ausentes: ' + ', '.join(sorted(required - set(df.columns))))
    df = df[df['Status'].map(norm) == 'FECHADO'].copy()
    df['data'] = pd.to_datetime(df['DATA'].astype(str).str.strip(), format='%d/%m/%Y', errors='coerce')
    invalid = int((df['data'].isna() | (df['data'].dt.year < 2020)).sum())
    df = df[df['data'].notna() & (df['data'].dt.year >= 2020)].copy()
    df['valor'] = df['Valor'].map(parse_brl)
    df['mes'] = df['data'].dt.strftime('%Y-%m')
    df['fisio'] = df['Fisioterapeuta'].map(canonical_name).replace('', 'Não informado')
    df['indicador'] = df['Indicação'].map(canonical_name).replace('', 'Não informado')
    df['origem'] = df['REF. INDICAÇÃO'].fillna('').astype(str).str.strip().replace('', 'Não informada')
    df['categoria'] = df['Serviço'].map(norm).map(lambda x: 'Reabilitação' if 'REABILITA' in x else ('Recovery' if 'RECOVERY' in x else 'Outros'))
    df['sessoes'] = pd.to_numeric(df.get('Sessões', pd.Series(index=df.index, dtype=str)).astype(str).str.replace(',', '.', regex=False), errors='coerce')
    df['fisio_key'] = df['fisio'].map(norm)
    df['indicador_key'] = df['indicador'].map(norm)
    return df, invalid

def metrics(frame):
    rehab = frame[frame['categoria'] == 'Reabilitação']
    n = len(frame)
    return {'valor': float(frame['valor'].sum()), 'vendas': n, 'ticket': float(frame['valor'].sum()) / n if n else 0,
            'longas': int((rehab['sessoes'] > 10).sum()), 'rehab': len(rehab),
            'percentual_longo': 100 * (rehab['sessoes'] > 10).sum() / len(rehab) if len(rehab) else None}

def team_name(value):
    return canonical_name(value)

st.title('XS Intelligence 2.7')
st.caption('Gestão comercial e desempenho compartilhado • Fonte: VENDAS • Atualização automática em até 5 minutos')
raw = None
if 'google_service_account' in st.secrets:
    try:
        raw = get_sales(st.secrets.get('spreadsheet_id', SPREADSHEET_ID), dict(st.secrets['google_service_account']))
    except Exception as exc:
        st.error('Falha ao acessar a planilha. Confira as permissões e os Secrets.')
        st.caption(f'Tipo do erro: {type(exc).__name__}')
if raw is None:
    uploaded = st.file_uploader('Carregar exportação da aba VENDAS (opcional)', type=['xlsx', 'csv'])
    if uploaded is None:
        st.stop()
    if uploaded.name.lower().endswith('.xlsx'):
        raw = pd.read_excel(uploaded, sheet_name='VENDAS', dtype=str)
    else:
        content = uploaded.getvalue()
        for sep in [None, ';', ',']:
            try:
                candidate = pd.read_csv(io.BytesIO(content), sep=sep, engine='python', dtype=str, encoding='utf-8-sig')
                if 'DATA' in candidate.columns:
                    raw = candidate
                    break
            except Exception:
                pass
if raw is None or raw.empty:
    st.warning('Não há dados para analisar.')
    st.stop()
try:
    df, invalid = prepare(raw)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
if df.empty:
    st.warning('Não há vendas fechadas com datas válidas.')
    st.stop()

with st.sidebar:
    st.header('Filtros compartilhados')
    months = sorted(df['mes'].unique())
    selected_months = st.multiselect('Meses', months, default=months[-3:])
    services = sorted(df['categoria'].unique())
    selected_services = st.multiselect('Serviços', services, default=services)
    origins = sorted(df['origem'].unique())
    selected_origins = st.multiselect('Origens', origins, default=origins)
    st.caption('O filtro de profissional é independente em cada aba para não confundir vendas e indicações.')

base = df[df['mes'].isin(selected_months) & df['categoria'].isin(selected_services) & df['origem'].isin(selected_origins)].copy()
if base.empty:
    st.warning('Sem registros para os filtros selecionados.')
    st.stop()
if invalid:
    st.warning(f'Qualidade dos dados: {invalid} venda(s) fechada(s) excluída(s) por data inválida.')

def operational_snapshot(all_sales):
    """KPIs sempre globais, sem filtros, usando a data local de Fortaleza."""
    today = datetime.now(ZoneInfo('America/Fortaleza')).date()
    dated = all_sales[all_sales['data'].dt.date <= today]
    start_week = today - timedelta(days=today.weekday())  # segunda-feira
    month_start = today.replace(day=1)
    week = dated[dated['data'].dt.date >= start_week]
    month = dated[dated['data'].dt.date >= month_start]
    return today, start_week, week, month


def daily_comparison(all_sales, today):
    """Curvas de faturamento acumulado por dia do mês (sem filtros laterais).

    Média: curvas acumuladas de meses completos pós-TS; meses sem venda contam
    como zero, e dias inexistentes no mês de referência não entram na média.
    """
    current = pd.Period(today, freq='M')
    previous = current - 1
    last_year = current - 12
    first_historical = pd.Period('2025-07', freq='M')
    historic_months = (list(pd.period_range(first_historical, previous, freq='M'))
                       if previous >= first_historical else [])
    clean = all_sales[all_sales['data'].dt.date <= today].copy()
    clean['periodo'] = clean['data'].dt.to_period('M')
    clean['dia'] = clean['data'].dt.day
    daily = clean.groupby(['periodo', 'dia'])['valor'].sum()

    def cumulative(month):
        total = 0.0
        result = {}
        for day in range(1, month.days_in_month + 1):
            total += float(daily.get((month, day), 0.0))
            result[day] = total
        return result

    curves = {month: cumulative(month) for month in
              set(historic_months + [current, previous, last_year])}
    output = []
    for day in range(1, current.days_in_month + 1):
        values = [curves[month][day] for month in historic_months
                  if day <= month.days_in_month]
        output.append({
            'Dia do mês': day,
            'Mês atual': curves[current].get(day) if day <= today.day else None,
            'Mês anterior': curves[previous].get(day),
            'Mesmo mês do ano anterior': curves[last_year].get(day)
            if last_year >= first_historical else None,
            'Média histórica pós-TS': sum(values) / len(values) if values else None,
        })
    totals = {
        'atual': curves[current].get(min(today.day, current.days_in_month), 0.0),
        'anterior': curves[previous][previous.days_in_month],
        'ano': curves[last_year][last_year.days_in_month]
        if last_year >= first_historical else None,
        'media': (sum(curves[month][month.days_in_month] for month in historic_months)
                  / len(historic_months)) if historic_months else None,
    }
    return pd.DataFrame(output), len(historic_months), previous, last_year, totals


def goal_panel(all_sales, today):
    """Current-month goals independent of sidebar filters."""
    current = pd.Period(today, freq='M')
    current_sales = all_sales[(all_sales['data'].dt.to_period('M') == current) &
                              (all_sales['data'].dt.date <= today)]
    total = float(current_sales['valor'].sum())
    st.subheader('Metas comerciais — mês corrente')
    a, b, c = st.columns(3)
    a.metric('Meta mínima da XS', brl(CLINIC_GOAL))
    b.metric('Faturamento da XS', brl(total))
    c.metric('Falta para a meta XS' if total < CLINIC_GOAL else 'Acima da meta XS',
             brl(abs(CLINIC_GOAL - total)))
    st.progress(min(max(total / CLINIC_GOAL, 0.0), 1.0),
                text=f'{100 * total / CLINIC_GOAL:.1f}% da meta XS')
    st.markdown('**Acompanhamento por fisioterapeuta**')
    cols = st.columns(2)
    for i, (name, target) in enumerate(GOALS.items()):
        sold = float(current_sales.loc[current_sales['fisio_key'] == norm(name), 'valor'].sum())
        remaining = max(0.0, target - sold)
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f'**{name}**')
                st.metric('Vendido no mês', brl(sold))
                st.caption(f'Meta: {brl(target)} · ' +
                           (f'Faltam {brl(remaining)}' if remaining else
                            f'Meta superada em {brl(sold-target)}'))
                st.progress(min(max(sold / target, 0.0), 1.0),
                            text=f'{100 * sold / target:.1f}% da meta')
    st.caption('Valores de vendas FECHADAS por fisioterapeuta. Metas individuais somam R$ 55.000; '
               'vendas de outros profissionais entram no faturamento da XS, mas não nas metas individuais. '
               'Indicadores independentes dos filtros laterais.')


def individual_cumulative(all_sales, today, name, kind, target=None):
    """Day-by-day cumulative lines; historical reference is previous six full months."""
    current = pd.Period(today, freq='M')
    previous = current - 1
    history_months = [current - n for n in range(6, 0, -1)]
    first_post_ts = pd.Period('2025-07', freq='M')
    history_months = [m for m in history_months if m >= first_post_ts]
    if kind == 'revenue':
        relevant = all_sales[all_sales['fisio_key'] == norm(name)]
        field, title = 'valor', 'Faturamento vendido acumulado'
    elif kind == 'count':
        relevant = all_sales[all_sales['fisio_key'] == norm(name)]
        field, title = 'count', 'Quantidade acumulada de vendas'
    else:
        relevant = all_sales[all_sales['indicador_key'] == norm(name)]
        field, title = 'valor', 'Faturamento acumulado das indicações'
    relevant = relevant[relevant['data'].dt.date <= today].copy()
    relevant['periodo'] = relevant['data'].dt.to_period('M')
    relevant['dia'] = relevant['data'].dt.day
    daily = (relevant.groupby(['periodo', 'dia'])['valor'].sum() if field == 'valor'
             else relevant.groupby(['periodo', 'dia']).size())
    def curve(month):
        total = 0.0
        result = {}
        for day in range(1, month.days_in_month + 1):
            total += float(daily.get((month, day), 0))
            result[day] = total
        return result
    curves = {m: curve(m) for m in set(history_months + [current, previous])}
    rows = []
    for day in range(1, current.days_in_month + 1):
        hist = [curves[m][day] for m in history_months if day <= m.days_in_month]
        row = {'Dia': day,
               'Mês atual': curves[current][day] if day <= today.day else None,
               'Mês anterior': curves[previous].get(day),
               'Média últimos 6 meses': sum(hist)/len(hist) if hist else None}
        if target is not None:
            row['Trajetória da meta'] = target * day / current.days_in_month
        rows.append(row)
    data = pd.DataFrame(rows)
    plotted = data.melt('Dia', var_name='Referência', value_name='Valor').dropna(subset=['Valor'])
    fig = px.line(plotted, x='Dia', y='Valor', color='Referência',
                  title=title, labels={'Valor': title},
                  category_orders={'Referência': ['Mês atual', 'Mês anterior',
                                                  'Média últimos 6 meses', 'Trajetória da meta']})
    fig.update_xaxes(dtick=1, range=[0.5, current.days_in_month + 0.5])
    fig.update_layout(hovermode='x unified', legend_title_text='Comparação')
    st.plotly_chart(fig, use_container_width=True)
    st.caption('Mês atual até hoje; mês anterior completo; média das curvas acumuladas dos '
               f'{len(history_months)} meses completos anteriores (incluindo meses sem vendas). '
               'Dias inexistentes não entram na média. ' +
               ('Linha de meta proporcional aos dias do mês.' if target is not None else ''))



# ---- Produção: dados de agenda exportados diariamente ----
PRODUCTION_GOALS = {'Lucas Marçal': 120, 'Lucas Valentim': 100, 'Victor': 90, 'Letícia': 40}
FULL_NAMES = {
    'LUCAS MARCAL ROCHA DA SILVA': 'Lucas Marçal',
    'LUCAS VALENTIM DE FREITAS': 'Lucas Valentim',
    'VICTOR MATHEUS LEITE MASCARENHAS FERREIRA': 'Victor',
    'LETICIA CARVALHO BEZERRA DE MENDONCA': 'Letícia',
}

@st.cache_data(ttl=300, show_spinner='Atualizando base de atendimentos...')
def get_appointments(sheet_id, credentials):
    import gspread
    client = gspread.service_account_from_dict(credentials)
    return client.open_by_key(sheet_id).worksheet('Base | Atendimentos').get_all_values()

def classify_appointment(service):
    label = norm(service)
    if 'VOUCHER' in label or 'AVALIACAO' in label or 'CRIOTERAPIA' in label:
        return 'Não remunerado'
    if 'FISIOTERAPIA' in label or 'RECOVERY' in label or 'FISIO LONGEVIDADE' in label:
        return 'Remunerado'
    return 'Não classificado'

def prepare_appointments(values):
    # A planilha histórica não tem cabeçalho fixo: a situação aparece em M ou N.
    rows = []
    for r in values:
        if len(r) < 10:
            continue
        name = FULL_NAMES.get(norm(r[8]))
        if not name:
            continue
        statuses = [r[i].strip() for i in (12, 13) if len(r) > i and r[i]]
        if 'Confirmado' not in statuses:
            continue
        dt = pd.to_datetime(str(r[0]).strip(), format='%d/%m/%Y', errors='coerce')
        if pd.isna(dt):
            continue
        rows.append((dt, name, str(r[9]), classify_appointment(r[9])))
    return pd.DataFrame(rows, columns=['data','fisio','servico','classe'])

def sold_sessions(sales, begin, end, name=None):
    x = sales[(sales['data'].dt.date >= begin) & (sales['data'].dt.date <= end)]
    if name:
        x = x[x['fisio'] == name]
    # Sessões desconhecidas NÃO são presumidas como 1; registrar separadamente.
    valid = x['sessoes'].notna() & (x['sessoes'] > 0)
    return int(x.loc[valid, 'sessoes'].sum()), int((~valid).sum())

def production_count(appointments, begin, end, name=None, classe='Remunerado'):
    if appointments.empty:
        return 0
    x = appointments[(appointments['data'].dt.date >= begin) & (appointments['data'].dt.date <= end)]
    if name:
        x = x[x['fisio'] == name]
    if classe:
        x = x[x['classe'] == classe]
    return len(x)

def ira_text(sold, attended):
    return f'{100 * sold / attended:.1f}%' if attended else '—'

def productivity_cumulative(appointments, name, today):
    st.markdown('#### Evolução de atendimentos remunerados — diário e acumulado')
    current = pd.Period(today, freq='M')
    previous = current - 1
    historic = [current - k for k in range(1, 7)]
    cutoff = today.day
    days = list(range(1, cutoff + 1))
    def day_counts(period):
        x = appointments[(appointments['fisio'] == name) &
                         (appointments['classe'] == 'Remunerado') &
                         (appointments['data'].dt.to_period('M') == period)]
        counts = x.groupby(x['data'].dt.day).size()
        return [float(counts.get(day, 0)) if day <= period.days_in_month else float('nan') for day in days]
    actual = day_counts(current)
    prior = day_counts(previous)
    history = [day_counts(p) for p in historic]
    historical_mean = []
    for i in range(len(days)):
        vals = [arr[i] for arr in history if not pd.isna(arr[i])]
        historical_mean.append(sum(vals) / len(vals) if vals else float('nan'))
    frame = pd.DataFrame({'Dia': days, 'Mês atual': actual,
                          'Mês anterior': prior, 'Média histórica (6 meses)': historical_mean})
    cumulative = frame.copy()
    for col in frame.columns[1:]:
        cumulative[col] = frame[col].fillna(0).cumsum()
        cumulative.loc[frame[col].isna(), col] = float('nan')
    x1, x2 = st.columns(2)
    with x1:
        st.plotly_chart(px.line(frame.melt(id_vars='Dia', var_name='Referência', value_name='Atendimentos'),
                                x='Dia', y='Atendimentos', color='Referência', markers=True,
                                title='Atendimentos por dia'), use_container_width=True)
    with x2:
        st.plotly_chart(px.line(cumulative.melt(id_vars='Dia', var_name='Referência', value_name='Acumulado'),
                                x='Dia', y='Acumulado', color='Referência', markers=True,
                                title='Atendimentos acumulados'), use_container_width=True)
    now_n = int(sum(actual))
    prev_n = sum(v for v in prior if not pd.isna(v))
    hist_n = sum(v for v in historical_mean if not pd.isna(v))
    a,b,c,d = st.columns(4)
    a.metric('Atendidos até hoje', now_n)
    b.metric('Mesmo período do mês anterior', int(prev_n), delta=f'{now_n-prev_n:+.0f}')
    c.metric('Média histórica até o mesmo dia', f'{hist_n:.1f}', delta=f'{now_n-hist_n:+.1f}')
    d.metric('Meta mensal', PRODUCTION_GOALS[name])
    st.caption('Média histórica: seis meses anteriores, dia a dia; datas inexistentes em meses curtos são ignoradas. '
               'Compare também dias úteis e feriados antes de interpretar diferenças.')

appointments = pd.DataFrame(columns=['data','fisio','servico','classe'])
appointments_error = None
if 'google_service_account' in st.secrets:
    try:
        appointment_values = get_appointments(st.secrets.get('spreadsheet_id', SPREADSHEET_ID),
                                               dict(st.secrets['google_service_account']))
        appointments = prepare_appointments(appointment_values)
    except Exception as exc:
        appointments_error = type(exc).__name__


visao, equipe, individual = st.tabs(['📊 Visão geral', '👥 Comparativo da equipe', '📈 Evolução individual'])

with visao:
    today, start_week, week_now, month_now = operational_snapshot(df)
    st.subheader('Pulso comercial — semana e mês corrente')
    st.caption('Indicadores globais, independentes dos filtros laterais. Consideram apenas vendas FECHADAS com data até hoje (horário de Fortaleza).')
    a, b, c, d = st.columns(4)
    a.metric('Vendas nesta semana (nº)', len(week_now))
    b.metric('Faturamento nesta semana', brl(float(week_now['valor'].sum())))
    c.metric('Vendas neste mês (nº)', len(month_now))
    d.metric('Faturamento neste mês', brl(float(month_now['valor'].sum())))
    st.caption(f'Semana: {start_week:%d/%m} a {today:%d/%m/%Y} (segunda a hoje) · Mês: 01/{today:%m} a {today:%d/%m/%Y}. Atualização da fonte: cache de até 5 minutos.')

    goal_panel(df, today)
    st.divider()

    st.subheader('Faturamento acumulado por dia — comparação histórica')
    comparison, historical_n, previous_period, last_year_period, totals = daily_comparison(df, today)
    if historical_n:
        a, b, c, d = st.columns(4)
        a.metric(f'Acumulado {today:%m/%Y} (até hoje)', brl(totals['atual']))
        b.metric(f'Total {previous_period.strftime("%m/%Y")}', brl(totals['anterior']))
        c.metric(f'Total {last_year_period.strftime("%m/%Y")}',
                 brl(totals['ano']) if totals['ano'] is not None else '—')
        d.metric('Média mensal histórica pós-TS',
                 brl(totals['media']) if totals['media'] is not None else '—')

        long_comparison = comparison.melt(
            id_vars='Dia do mês', var_name='Referência',
            value_name='Faturamento acumulado (R$)'
        ).dropna(subset=['Faturamento acumulado (R$)'])
        fig = px.line(
            long_comparison, x='Dia do mês', y='Faturamento acumulado (R$)',
            color='Referência', markers=True,
            category_orders={'Referência': [
                'Mês atual', 'Mês anterior', 'Mesmo mês do ano anterior',
                'Média histórica pós-TS']},
            title='Faturamento acumulado desde o dia 1º de cada mês',
        )
        fig.update_xaxes(dtick=1, range=[0.5, comparison['Dia do mês'].max() + 0.5])
        fig.update_traces(hovertemplate='Dia %{x}<br>Acumulado: R$ %{y:,.2f}<extra>%{fullData.name}</extra>')
        fig.update_layout(hovermode='x unified', legend_title_text='Período')
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f'Mês atual: {today:%m/%Y} (até {today:%d/%m}); '
            f'mês anterior: {previous_period.strftime("%m/%Y")} (completo); '
            f'mesmo mês do ano passado: {last_year_period.strftime("%m/%Y")} (completo). '
            f'Média histórica: {historical_n} meses completos desde julho/2025, '
            'incluindo meses sem vendas. Gráfico independente dos filtros laterais.'
        )
        st.caption('Cada ponto soma as vendas desde o dia 1º. Dias sem vendas mantêm o acumulado anterior. Dias inexistentes em meses curtos não são comparados; dias futuros do mês atual não aparecem.')
    else:
        st.info('Ainda não há meses completos suficientes para calcular a média histórica pós-TS.')

    st.divider()
    st.subheader('Análise do período selecionado')
    m = metrics(base)
    cols = st.columns(4)
    cols[0].metric('Valor vendido', brl(m['valor']))
    cols[1].metric('Vendas fechadas', f"{m['vendas']:,}".replace(',', '.'))
    cols[2].metric('Ticket médio', brl(m['ticket']))
    cols[3].metric('Reabilitações >10 sessões', f"{m['longas']}/{m['rehab']}")
    st.caption(f"Período dos registros: {base['data'].min():%d/%m/%Y} a {base['data'].max():%d/%m/%Y}. Meses em andamento são parciais.")
    left, right = st.columns(2)
    with left:
        st.subheader('Evolução mensal')
        monthly = base.groupby('mes', as_index=False).agg(valor=('valor', 'sum'), vendas=('valor', 'size'))
        st.plotly_chart(px.bar(monthly, x='mes', y='valor', labels={'mes': 'Mês', 'valor': 'Valor vendido (R$)'}), use_container_width=True)
    with right:
        st.subheader('Mix de serviços')
        mix = base.groupby('categoria', as_index=False)['valor'].sum()
        st.plotly_chart(px.pie(mix, names='categoria', values='valor', hole=.5), use_container_width=True)
    st.subheader('Origem das vendas')
    source = base.groupby('origem', as_index=False).agg(valor=('valor', 'sum'), vendas=('valor', 'size')).sort_values('valor', ascending=False)
    st.dataframe(source.rename(columns={'origem':'Origem', 'valor':'Valor vendido (R$)', 'vendas':'Vendas'}), hide_index=True, use_container_width=True)

def service_stats(frame, prefix):
    result = {}
    for category, slug in [('Reabilitação', 'Reabilitação'), ('Recovery', 'Recovery')]:
        part = frame[frame['categoria'] == category]
        result[f'{prefix} {slug} (nº)'] = len(part)
        result[f'{prefix} {slug} (R$)'] = float(part['valor'].sum())
        result[f'{prefix} Ticket {slug} (R$)'] = float(part['valor'].mean()) if len(part) else None
    return result


def month_series(frame, all_months, label):
    grouped = frame.groupby('mes').agg(faturamento=('valor', 'sum'), quantidade=('valor', 'size'))
    grouped = grouped.reindex(all_months, fill_value=0).reset_index().rename(columns={'index': 'mes'})
    grouped['Dimensão'] = label
    return grouped


with equipe:
    st.subheader('Ranking e comparativo dos fisioterapeutas')
    st.caption('Vendas fechadas = coluna Fisioterapeuta. Indicações geradas = coluna Indicação. Uma venda pode constar nas duas dimensões; não some seus faturamentos.')
    available = sorted(set(base['fisio'].map(team_name)) | set(base['indicador'].map(team_name)))
    defaults = [name for name in TEAM if name in available]
    chosen = st.multiselect('Profissionais a comparar', available, default=defaults or available, key='team_select')
    rows = []
    for name in chosen:
        sold = base[base['fisio_key'] == norm(name)]
        referred = base[base['indicador_key'] == norm(name)]
        ms, mi = metrics(sold), metrics(referred)
        row = {'Fisioterapeuta': name,
               'Vendas fechadas (nº)': ms['vendas'], 'Faturamento vendido (R$)': ms['valor'],
               'Ticket vendas (R$)': ms['ticket'] if ms['vendas'] else None,
               'Indicações geradas (nº)': mi['vendas'], 'Faturamento indicado (R$)': mi['valor'],
               'Ticket indicações (R$)': mi['ticket'] if mi['vendas'] else None,
               'Reabilitações >10 (%)': round(ms['percentual_longo'], 1) if ms['percentual_longo'] is not None else None,
               'Sessões vendidas (informadas)': float(sold['sessoes'].sum()) if sold['sessoes'].notna().any() else None}
        row.update(service_stats(sold, 'Vendas'))
        row.update(service_stats(referred, 'Indicações'))
        rows.append(row)
    comp = pd.DataFrame(rows)
    if comp.empty:
        st.info('Selecione ao menos um profissional.')
    else:
        money_cols = [c for c in comp.columns if '(R$)' in c]
        cfg = {c: st.column_config.NumberColumn(format='R$ %.2f') for c in money_cols}
        cfg['Reabilitações >10 (%)'] = st.column_config.NumberColumn(format='%.1f%%')
        st.dataframe(comp.sort_values('Faturamento vendido (R$)', ascending=False), use_container_width=True,
                     hide_index=True, column_config=cfg)
        ranking_options = [c for c in comp.columns if c not in ('Fisioterapeuta',) and c != 'Sessões vendidas (informadas)']
        ranking_options += ['Sessões vendidas (informadas)']
        ranking = st.selectbox('Ranking por indicador', ranking_options)
        ranked = comp.sort_values(ranking, ascending=False, na_position='last')
        st.plotly_chart(px.bar(ranked, x='Fisioterapeuta', y=ranking, text_auto='.2s',
                               title=f'Ranking — {ranking}'), use_container_width=True)
        comparison = comp.melt(id_vars='Fisioterapeuta',
                               value_vars=['Faturamento vendido (R$)', 'Faturamento indicado (R$)'],
                               var_name='Dimensão', value_name='Faturamento (R$)')
        st.plotly_chart(px.bar(comparison, x='Fisioterapeuta', y='Faturamento (R$)', color='Dimensão',
                               barmode='group', title='Vendas fechadas x indicações geradas'),
                        use_container_width=True)
    st.info('Atendimentos realizados e taxas por 100 atendimentos dependem da aba Base | Atendimentos. Conversão depende do registro dos leads atribuídos.')

with individual:
    st.subheader('Desempenho individual: vendas fechadas e indicações geradas')
    people = sorted(set(df['fisio'].map(team_name)) | set(df['indicador'].map(team_name)))
    initial = next((name for name in TEAM if name in people), people[0])
    selected = st.selectbox('Profissional', people, index=people.index(initial))
    today_individual = datetime.now(ZoneInfo('America/Fortaleza')).date()
    if selected in GOALS:
        month_sales = df[(df['data'].dt.to_period('M') == pd.Period(today_individual, freq='M')) &
                         (df['data'].dt.date <= today_individual) &
                         (df['fisio_key'] == norm(selected))]
        earned = float(month_sales['valor'].sum())
        goal = GOALS[selected]
        remaining = max(0.0, goal - earned)
        st.subheader('Meta individual — mês corrente')
        g1, g2, g3, g4 = st.columns(4)
        g1.metric('Meta mensal', brl(goal))
        g2.metric('Vendido no mês', brl(earned))
        g3.metric('Falta para a meta' if remaining else 'Acima da meta',
                  brl(remaining if remaining else max(0.0, earned-goal)))
        g4.metric('Meta atingida', f'{100 * earned / goal:.1f}%')
        st.progress(min(max(earned/goal, 0.0), 1.0))
        days_left = (pd.Period(today_individual, freq='M').end_time.date() - today_individual).days
        if remaining and days_left > 0:
            st.caption(f'Ritmo necessário: {brl(remaining / days_left)} por dia restante '
                       f'({days_left} dias corridos).')
        elif remaining:
            st.caption('Último dia do mês: meta ainda não atingida.')
        else:
            st.caption('Meta mensal atingida.')
        st.caption('Metas do mês corrente independentes dos filtros laterais.')
    st.subheader('Curvas acumuladas — desempenho individual')
    st.caption('Os gráficos abaixo são sempre do mês corrente e independem dos filtros laterais.')
    individual_cumulative(df, today_individual, selected, 'revenue', GOALS.get(selected))
    individual_cumulative(df, today_individual, selected, 'count')
    individual_cumulative(df, today_individual, selected, 'referrals')
    st.divider()
    sold = base[base['fisio_key'] == norm(selected)]
    referred = base[base['indicador_key'] == norm(selected)]
    st.caption('Indicadores abaixo respeitam os meses, serviços e origens selecionados na lateral.')
    ms, mi = metrics(sold), metrics(referred)
    left, right = st.columns(2)
    for column, label, stats in [(left, 'VENDAS FECHADAS', ms), (right, 'INDICAÇÕES GERADAS', mi)]:
        with column:
            st.markdown(f'#### {label}')
            st.metric('Faturamento (R$)', brl(stats['valor']))
            a, b = st.columns(2)
            a.metric('Quantidade de vendas', stats['vendas'])
            b.metric('Ticket médio', brl(stats['ticket']) if stats['vendas'] else '—')
    summary = []
    for label, frame in [('Vendas fechadas', sold), ('Indicações geradas', referred)]:
        for category in ['Reabilitação', 'Recovery']:
            part = frame[frame['categoria'] == category]
            summary.append({'Dimensão': label, 'Serviço': category, 'Vendas (nº)': len(part),
                            'Faturamento (R$)': float(part['valor'].sum()),
                            'Ticket médio (R$)': float(part['valor'].mean()) if len(part) else None})
    st.subheader('Quantidade, faturamento e ticket por serviço')
    services_summary = pd.DataFrame(summary)
    st.dataframe(services_summary, use_container_width=True, hide_index=True,
                 column_config={'Faturamento (R$)': st.column_config.NumberColumn(format='R$ %.2f'),
                                'Ticket médio (R$)': st.column_config.NumberColumn(format='R$ %.2f')})
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.bar(services_summary, x='Serviço', y='Vendas (nº)', color='Dimensão',
                               barmode='group', title='Quantidade de vendas por serviço', text_auto=True),
                        use_container_width=True)
    with c2:
        st.plotly_chart(px.bar(services_summary, x='Serviço', y='Faturamento (R$)', color='Dimensão',
                               barmode='group', title='Faturamento por serviço'), use_container_width=True)
    st.subheader('Evolução mensal — vendas x indicações')
    st.caption('Histórico completo com os filtros de serviço e origem; o filtro de meses da lateral não limita este gráfico.')
    historical = df[df['categoria'].isin(selected_services) & df['origem'].isin(selected_origins)].copy()
    sold_h = historical[historical['fisio_key'] == norm(selected)]
    referred_h = historical[historical['indicador_key'] == norm(selected)]
    if sold_h.empty and referred_h.empty:
        st.info('Sem histórico para este profissional nos filtros escolhidos.')
    else:
        first = min([frame['data'].min() for frame in (sold_h, referred_h) if not frame.empty])
        last = historical['data'].max()
        month_range = pd.period_range(first.to_period('M'), last.to_period('M'), freq='M').astype(str).tolist()
        history = pd.concat([month_series(sold_h, month_range, 'Vendas fechadas'),
                             month_series(referred_h, month_range, 'Indicações geradas')], ignore_index=True)
        st.plotly_chart(px.line(history, x='mes', y='faturamento', color='Dimensão', markers=True,
                                labels={'mes': 'Mês', 'faturamento': 'Faturamento (R$)'}),
                        use_container_width=True)
        st.plotly_chart(px.bar(history, x='mes', y='quantidade', color='Dimensão', barmode='group',
                               title='Quantidade mensal de vendas e indicações',
                               labels={'mes': 'Mês', 'quantidade': 'Vendas (nº)'}), use_container_width=True)
        st.dataframe(history.rename(columns={'mes': 'Mês', 'faturamento': 'Faturamento (R$)',
                                             'quantidade': 'Vendas (nº)'}),
                     hide_index=True, use_container_width=True)
        st.caption('Meses sem vendas são exibidos com zero. O último mês pode estar incompleto.')

st.divider()
st.caption('Resultados profissionais compartilhados. Não são exibidos dados pessoais de pacientes. Proteja o acesso ao aplicativo: a URL pública não equivale a controle de acesso.')


# ---- Blocos adicionais (mesmas três abas; preservam gráficos e filtros existentes) ----
now_prod = datetime.now(ZoneInfo('America/Fortaleza')).date()
month_begin = now_prod.replace(day=1)
week_begin = now_prod - timedelta(days=now_prod.weekday())
with visao:
    st.divider()
    st.subheader('🏥 Produtividade da fisioterapia — mês corrente')
    if appointments_error:
        st.warning(f'Não foi possível atualizar os atendimentos ({appointments_error}). Confira o acesso à aba Base | Atendimentos.')
    elif appointments.empty:
        st.info('Nenhum atendimento confirmado encontrado na base.')
    else:
        latest = appointments['data'].max().date()
        st.caption(f'Última data confirmada encontrada: {latest:%d/%m/%Y}. '
                   'Indicadores independentes dos filtros laterais. Somente agendamentos Confirmados.')
        end = min(now_prod, latest)
        team_paid = production_count(appointments, month_begin, end)
        team_free = production_count(appointments, month_begin, end, classe='Não remunerado')
        sold, missing = sold_sessions(df, month_begin, now_prod)
        a,b,c,d = st.columns(4)
        a.metric('Atendimentos remunerados', team_paid)
        b.metric('Atendimentos não remunerados', team_free)
        c.metric('Sessões vendidas no mês', sold)
        d.metric('IRA mensal da equipe', ira_text(sold, team_paid))
        st.progress(min(team_paid / sum(PRODUCTION_GOALS.values()), 1.0),
                    text=f'{team_paid} de {sum(PRODUCTION_GOALS.values())} atendimentos remunerados da meta da equipe')
        st.caption(f'Vendas com quantidade de sessões ausente ou inválida: {missing}. '
                   'IRA é indicador de fluxo comercial/produtivo, não saldo exato de sessões em carteira.')
        lines = []
        for name, goal in PRODUCTION_GOALS.items():
            paid = production_count(appointments, month_begin, end, name)
            free = production_count(appointments, month_begin, end, name, 'Não remunerado')
            sessions, unknown = sold_sessions(df, month_begin, now_prod, name)
            lines.append({'Fisioterapeuta':name,'Remunerados':paid,'Não remunerados':free,
                          'Meta':goal,'Atingimento (%)':round(100*paid/goal,1),
                          'Sessões vendidas':sessions,'IRA (%)':round(100*sessions/paid,1) if paid else None,
                          'Vendas sem sessões':unknown})
        st.dataframe(pd.DataFrame(lines), use_container_width=True, hide_index=True)
        if not appointments[appointments['classe']=='Não classificado'].empty:
            st.warning('Há serviços confirmados ainda não classificados. Revise antes de interpretar a produção total.')

with equipe:
    st.divider()
    st.subheader('⚖️ Reposição semanal e mensal da agenda')
    if not appointments.empty:
        records = []
        end = min(now_prod, appointments['data'].max().date())
        for name in PRODUCTION_GOALS:
            for label, begin in [('Semana atual',week_begin),('Mês atual',month_begin)]:
                paid = production_count(appointments, begin, end, name)
                sold, missing = sold_sessions(df, begin, now_prod, name)
                records.append({'Profissional':name,'Período':label,'Sessões vendidas':sold,
                                'Atendimentos remunerados':paid,'Saldo do período':sold-paid,
                                'IRA (%)':round(100*sold/paid,1) if paid else None,
                                'Vendas sem nº sessões':missing})
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
        st.caption('Atribuição: vendas por profissional que fechou; atendimentos por profissional que executou. '
                   'Um IRA abaixo de 100% isoladamente não demonstra perda futura de agenda.')
    else:
        st.info('Aguardando conexão com a Base | Atendimentos.')

with individual:
    st.divider()
    st.subheader('🏥 Produtividade individual e reposição da agenda')
    if selected in PRODUCTION_GOALS and not appointments.empty:
        end = min(now_prod, appointments['data'].max().date())
        for label, begin in [('Semana atual', week_begin), ('Mês atual', month_begin)]:
            sold, missing = sold_sessions(df, begin, now_prod, selected)
            paid = production_count(appointments, begin, end, selected)
            free = production_count(appointments, begin, end, selected, 'Não remunerado')
            st.markdown(f'**{label}**')
            a,b,c,d = st.columns(4)
            a.metric('Sessões vendidas', sold)
            b.metric('Atendimentos remunerados', paid)
            c.metric('Não remunerados', free)
            d.metric('IRA', ira_text(sold, paid))
            if missing:
                st.caption(f'{missing} venda(s) sem número válido de sessões no período.')
        productivity_cumulative(appointments, selected, now_prod)
    elif selected not in PRODUCTION_GOALS:
        st.info('Acompanhamento de produção disponível para os quatro fisioterapeutas principais.')
    else:
        st.info('Aguardando dados de atendimentos para mostrar a evolução individual.')
