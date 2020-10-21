import base64
import os
import random
import urllib
from io import BytesIO

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import streamlit as st
import xlsxwriter
from branca.element import MacroElement, Template
from PIL import Image
from streamlit_folium import folium_static
from unidecode import unidecode


@ st.cache(allow_output_mutation = True)
def load_data():
	# df= pd.read_csv('../base_trabalho_comum.csv')
	df=pd.read_csv('data/df_producao.csv')
	return df


def definir_tribunal(opc, df):

	# Aquelas coisas lá dos três tipos de justiça/área
	dict_siglas={'Justiça Federal': 'TRF',
                'Justiça do Trabalho': 'TRT',
                'Justiça Estadual': 'TJ'}


	# Transformar o label bonitinho de escolha do usuário na sigla que ta no dataframe
	opc = dict_siglas[opc]

	# Pega todos as tribunais daquele determinado tipo de tribunal
	list_tribunal = [i for i in df['siglaTribunal'].unique() if i.startswith(opc)]
	df_tribunal = df[df['siglaTribunal'].isin(list_tribunal)].copy()


	# Se a opção do tribunal for TRF ou TJ então tem Primeiro Grau e Juizado Especial
	if(opc != 'TRT'):
		opc_grau = st.sidebar.selectbox(
		    'Grau', ['Primeiro Grau', 'Juizado Especial'])

		if(opc_grau == "Primeiro Grau"):
			df_tribunal_grau=df_tribunal[df_tribunal.grau == 'G1']
			opc_grau="G1"
		else:
			df_tribunal_grau=df_tribunal[df_tribunal.grau == 'JE']
			opc_grau="JE"

	else:
		df_tribunal_grau=df_tribunal.copy()
		opc_grau="null"

	return df_tribunal_grau, opc_grau



def definir_assuntos(opc, df):
	# Se a pessoa não escolher nenhuma opção de direito, filtra os assuntos que representem
	# pelo menos 0,1% do total de assuntos e continua.
	if(opc == " - "):
	    assuntos=df['assunto_nivel_2'].value_counts(
	        normalize = True).loc[lambda x: x > 0.001]
	    default_p= pd.Series(0, index=[" - "])
	    assuntos= assuntos.add(default_p).sort_index().index

	    df_direitos= df.copy()

	# Se a pessoa escolhe um tipo de direito, os assuntos a serem mostrados em seguida
	# irão corresponder aos assuntos relacionados a esse tipo de direito.
	else:
		df_direitos= df[df['assunto_nivel_1'] == opc].copy()
		assuntos= df_direitos['assunto_nivel_2'].sort_values().unique()
		assuntos= np.insert(assuntos, 0, " - ", axis=0)

	return df_direitos, assuntos



def filtrar_opcoes(campo, lista_geral):
	if(campo == " - "):
		campo= lista_geral
	else:
		campo= [campo]

	return campo

def definir_cores(element, media):
	if(element > media):
		return 'red'
	elif(element == media):
		return 'yellow'
	elif(element < media):
		return 'green'


def dados_para_mapa(df):
	# Arquivo com as coordenadas das localidades no Brasil
	shapefile= gpd.read_file("shapefile_coordenadas/BR_Localidades_2010_v1.shp")

	# Selecionando as colunas que contém informações sobre cidades
	columns = ['CD_GEOCODM', 'NM_MUNICIP', 'LONG', 'LAT']
	localidade_cidades= shapefile[shapefile['NM_CATEGOR'] == 'CIDADE'][columns]

	# Alterando o nome e tipo da coluna de código dos municípios para posterior merge
	data_changed= df.copy()
	data_changed= data_changed.rename(
	    columns={'dadosBasicos.orgaoJulgador.codigoMunicipioIBGE': 'CD_GEOCODM'})
	data_changed.reset_index(drop=True, inplace=True)
	data_changed = data_changed.astype({'CD_GEOCODM': str})

	# Padronizando o registro de nome do orgão julgador dos processos
	data_changed['dadosBasicos.orgaoJulgador.nomeOrgao'] = [
	    str(x).upper() for x in data_changed['dadosBasicos.orgaoJulgador.nomeOrgao']]
	data_changed['dadosBasicos.orgaoJulgador.nomeOrgao'] = [
	    unidecode(x) for x in data_changed['dadosBasicos.orgaoJulgador.nomeOrgao']]

	# Merge entre 'data_changed' e 'localidade_cidades' para adicionar as coordenadas aos respectivos processos
	# Considerando apenas os processos que contém as datas de ajuizamento e a primeira sentença
	columns = ['dadosBasicos.orgaoJulgador.codigoOrgao', 'dadosBasicos.orgaoJulgador.nomeOrgao','data_ajuizamento_ok','data_primeira_sentenca_ok','CD_GEOCODM','NM_MUNICIP','LONG','LAT']
	df_processos = data_changed[(~data_changed['data_ajuizamento_ok'].isna()) & (
	    ~data_changed['data_primeira_sentenca_ok'].isna())].merge(localidade_cidades, on='CD_GEOCODM',)[columns]

	# Convertendo as datas para o padrão datetime
	df_processos['data_ajuizamento_ok'] = pd.to_datetime(
	    df_processos['data_ajuizamento_ok'], format='%Y-%m-%d', errors='coerce')
	df_processos['data_primeira_sentenca_ok'] = pd.to_datetime(
	    df_processos['data_primeira_sentenca_ok'], format='%Y-%m-%d', errors='coerce')

	# Retirando períodos inconsistentes entre data de ajuizamento e data de sentença
	df_processos = df_processos[~(df_processos['data_ajuizamento_ok'] > df_processos['data_primeira_sentenca_ok'])]
	df_processos.reset_index(drop=True, inplace=True)

	# Subtraindo a data de ajuizamento da data de sentença para extrair os dias
	df_processos['dias_ate_sentenca'] = [(i-j).days for i, j in zip(df_processos['data_primeira_sentenca_ok'],df_processos['data_ajuizamento_ok'])]

	# Agrupando os processos para calcular a média de dias até a primeira sentença, para cada vara
	grouped_data = df_processos.groupby(['dadosBasicos.orgaoJulgador.codigoOrgao', 'dadosBasicos.orgaoJulgador.nomeOrgao','CD_GEOCODM','NM_MUNICIP','LONG','LAT'])['dias_ate_sentenca'].mean().astype(int).reset_index(name='media_de_dias_ate_sentenca')

	# Função para alterar as coordenadas de varas no mesmo município, para fins de visualização no mapa
	def alterar_coordenadas(df_to_change):
		if df_to_change.shape[0] > 1:
			for index, row in df_to_change.iterrows():
				df_to_change.loc[index, 'LAT'] = df_to_change.loc[index,'LAT'] + random.uniform(0.01, 0.001)
				df_to_change.loc[index, 'LONG'] = df_to_change.loc[index,'LONG'] + random.uniform(0.01, 0.001)
		return df_to_change

	# Processando as varas por município
	finais = []
	aux = grouped_data.groupby('CD_GEOCODM')
	for municipio in aux.groups.keys():
		finais.append(alterar_coordenadas(
		    aux.get_group(municipio).reset_index(drop=True)))

	# Dados para a elaboração do mapa
	data_to_map = pd.concat(finais, ignore_index=True)

	# Ordenar os dados pelo tempo médio
	data_to_map = data_to_map.sort_values(by='media_de_dias_ate_sentenca')
	return data_to_map



def gerar_mapa(df, cor, opcao):
	# Quartis
	num_quantiles = 4

	radius_labels = [100, 200,300,400]
	df['radius'] = pd.qcut(df['media_de_dias_ate_sentenca'],
	                       q=num_quantiles, labels=radius_labels[-num_quantiles:])

	if(opcao == "Mapa"):
		# Divisão dos dados para visualização no mapa
		color_labels = ['green', 'yellow','orange','red']
		df['color'] = pd.qcut(df['media_de_dias_ate_sentenca'],
		                      q=num_quantiles, labels=color_labels[:num_quantiles])

		if(cor != " - "):
			df = df[df['color'] == cor]

	if(opcao == "Comparação"):
		df['color'] = df['media_de_dias_ate_sentenca'].apply(
		    definir_cores, media=int(media_nacional))




	# Bubble map do tempo médio até sentença para as varas constituintes
	m = folium.Map([-13.923403897723334, -49.92187499999999], zoom_start=4)

	for i in range(0, len(df)):
		folium.Circle(
			location = [df.iloc[i]['LAT'], df.iloc[i]['LONG']],
			popup = folium.Popup(u'Tempo: '+str(df.iloc[i]['media_de_dias_ate_sentenca'])+' dias',parse_html=True,max_width='100'),
			tooltip = df.iloc[i]['dadosBasicos.orgaoJulgador.nomeOrgao'],
			radius = int(df.iloc[i]['radius']),
			color = df.iloc[i]['color'],
			fill = True,
			fill_color = df.iloc[i]['color']
		).add_to(m)


	folium_static(m)
	return df

def to_excel(df):
    output= BytesIO()
    writer = pd.ExcelWriter(output, engine ='xlsxwriter')
    df.to_excel(writer, sheet_name ='Sheet1')
    writer.save()
    processed_data= output.getvalue()
    return processed_data

def get_table_download_link(df):
    val= to_excel(df)
    b64 = base64.b64encode(val)
    return f'<a href="data:application/octet-stream;base64,{b64.decode()}" download="varas_selecionadas.xlsx">Download arquivo Excel</a>'

"""
----------------------------------------------------------------------------------------------
"""


df= load_data()

st.sidebar.title('Desafio CNJ')
# st.sidebar.subheader("Escolha aí:")

opcao= st.sidebar.radio(' ', ('Mapa', 'Comparação'))
opc_tribunal = st.sidebar.selectbox('Justiça', ['Justiça Federal', 'Justiça do Trabalho', 'Justiça Estadual'])


df_tribunal_grau, opc_grau= definir_tribunal(opc_tribunal, df)


lista_direitos= df_tribunal_grau['assunto_nivel_1'].sort_values().unique()
lista_direitos = np.insert(lista_direitos, 0, " - ", axis =0)

# Dropdown com as opções de direitos
opc_direito= st.sidebar.selectbox('Assunto nível 1', lista_direitos)

df_direitos, assuntos= definir_assuntos(opc_direito, df_tribunal_grau)

# Dropdown com as opções de assuntos
opc_assunto1= st.sidebar.selectbox('Assunto nível 2', assuntos)

if(opc_assunto1 != " - "):
	assuntos2= df_direitos[df_direitos['assunto_nivel_2'] == opc_assunto1]['assunto_principal'].sort_values().unique()
	assuntos2 = np.insert(assuntos2, 0, " - ", axis =0)

else:
	assuntos2 = df_direitos['assunto_principal'].value_counts().loc[lambda x : x > 0.001]
	default_p= pd.Series(0, index=[" - "])
	assuntos2=  assuntos2.add(default_p).sort_index().index


# Dropdown com as opções de assuntos
opc_assunto2= st.sidebar.selectbox('Assunto nível 3', assuntos2)
# df_assuntos = df_direitos[df_direitos['assunto_principal'] == opc_assunto].copy()

opc_direito= filtrar_opcoes(opc_direito, lista_direitos)
opc_assunto1= filtrar_opcoes(opc_assunto1, assuntos)
opc_assunto2= filtrar_opcoes(opc_assunto2, assuntos2)

df_output= df_tribunal_grau[(df_tribunal_grau['assunto_nivel_1'].isin(opc_direito)) &
							(df_tribunal_grau['assunto_nivel_2'].isin(opc_assunto1)) &
							(df_tribunal_grau['assunto_principal'].isin(opc_assunto2))]




"""
----------------------------------------------------------------------------------------------
"""
if(opcao == "Comparação"):

	st.title("Comparação do tempo até sentença em ações não criminais")

	# st.write(df_output.columns)
	media_nacional= df_output['n_dias_ate_sentenca'].mean()
	st.write(
	    f"A média de tempo, em escala nacional, para o tipo de processo escolhido através dos filtros é de {media_nacional:.2f} dias")

	dados_mapa= dados_para_mapa(df_output)

	opc_cor= " - "
	dados_processados= gerar_mapa(dados_mapa, opc_cor, opcao)

	legendac= Image.open('legendacomparacao.png')
	st.image(legendac, width=700)


	# st.write(legenda)

else:

	st.title("Mapa do tempo até sentença em ações não criminais")

	dados_mapa= dados_para_mapa(df_output)

	# st.write("Verde - tempo médio <= 25% das amostras \n\n Amarelo - tempo médio <= 50% das amostras")
	# st.write("Laranja - tempo médio <= 75% das amostras \n\n Vermelho - tempo médio > 75% das amostras")

	opc_cor = st.sidebar.selectbox('Filtrar através de cores:', (' - ', 'Verde', 'Amarelo', 'Laranja', 'Vermelho'))
	dict_colors = {'Verde': 'green',
					'Amarelo':'yellow',
					'Laranja':'orange',
					'Vermelho':'red'}
	
	if(opc_cor != " - "):
		opc_cor = dict_colors[opc_cor]
	
	dados_processados = gerar_mapa(dados_mapa, opc_cor, opcao)
	dados_processados = dados_processados.astype({'color':'str','radius':'int64'})

	legenda = Image.open('legendamapa.png')
	st.image(legenda, width=700)

	st.title("Relatório \n\n")
	
	dados_relatorio = dados_processados.copy()
	dados_relatorio.columns = ['codigo_orgao_julgador', 'nome_orgao_julgador', 'geocodigo', 'nome_municipio', 
													'long', 'lat', 'media_de_dias_ate_sentenca', 'cor', 'radius']

	st.dataframe(dados_relatorio)

	st.markdown(get_table_download_link(dados_relatorio), unsafe_allow_html=True)
