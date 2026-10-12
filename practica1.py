
#=================================================================================
# Dashboard electoral CIS 3577 — Redisseny d'un "junkchart" (Pràctica 1, MIV · URV)
# Autora: Maria Enrich Capo
#=================================================================================

import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, ctx, dcc, html

# ----------------------------------------------------------------------------
# 0. CONFIGURACIÓ
# ----------------------------------------------------------------------------
CSV_PATH = "3577_etiq.csv"
GEOJSON_PATH = "spain-communities.geojson"
GEOJSON_URL = ("https://raw.githubusercontent.com/codeforgermany/click_that_hood/"
               "main/public/data/spain-communities.geojson")

# Segons la fitxa tècnica del CIS: PESO s'aplica a la mostra en conjunt (ajusta també per estudis)
# i PESOCCAA és la ponderació per a l'estimació a nivell de cada autonomia (sense ajust per estudis).
PESO_ESTATAL = "PESO"        # ponderació per a resultats estatals
PESO_AUTONOMIC = "PESOCCAA"  # ponderació per a resultats dins de cada CCAA
DATES_CAMP = "1–4 de setembre de 2026"  # treball de camp (fitxa tècnica)
MOSTRA_PETITA = 50           # per sota d'aquest n avisem que el resultat és poc fiable
CAP_AVANTATGE = 20           # avantatge (en punts) a partir del qual el color del mapa és ja el més intens
T_MIN = 0.35                 # intensitat mínima del color (empat): 0 = blanc, 1 = color pur

TOT_ESP = "ESP"              # codi especial: vista general de tot Espanya
CCAA_INICIAL = TOT_ESP       # en obrir l'app es veu el gràfic general

#Colors associats a cada partit (clau:valor)
COLORS = {
    "PSOE": "#EF1C27", "PP": "#0056A3", "VOX": "#9AD85A", "Sumar": "#E51C55",
    "Podemos": "#6B2E68", "ERC": "#FFB232", "Junts": "#00C3B2", "EH Bildu": "#00A29C",
    "BNG": "#8FB8D8", "EAJ-PNV": "#2E7D4F", "Se Acabó la Fiesta": "#B8860B",
    "Altres partits": "#8C8C8C",        
    "No expressa partit": "#D3D3D3",   
}
PARTITS = [p for p in COLORS if p not in ("Altres partits", "No expressa partit")]
RESIDUALS = ["Altres partits", "No expressa partit"] 


#Terminologia alineada amb el CIS: «% sobre censo» = totes les persones entrevistades.
BASES_ETIQ = {"tots": "Sobre el cens (totes les persones entrevistades)",
              "expressat": "Sobre qui declara partit"}
TITOL_Y = {"tots": "% sobre el cens",
           "expressat": "% sobre qui declara partit"}

#Barreja un color amb blanc. t=1 -> color pur; t=0 -> blanc
def mescla(color_hex, t):
    r, g, b = (int(color_hex[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(255 + (c - 255) * t) for c in (r, g, b))

#Color de text amb bon contrast: blanc sobre fons foscos, negre sobre fons clars
def text_sobre(fons_hex):
    r, g, b = (int(fons_hex[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    contrast_blanc = 1.05 / (lum + 0.05)
    return "#FFFFFF" if contrast_blanc >= 4.0 else "#111111"

#Avantatge en punts -> valor t reb la mescla (va de T_MIN (0.35) a 1)
def intensitat(avantatge):
    return T_MIN + (1 - T_MIN) * min(avantatge, CAP_AVANTATGE) / CAP_AVANTATGE


# ----------------------------------------------------------------------------
# 1. PREPROCESSAMENT
# ----------------------------------------------------------------------------
# 1.1. NETEJA I TIPATGE ------------------------------------------------------
#  - El CSV és UTF-8 amb BOM: amb 'latin1' sortiria "AndalucÃ­a".
#  - Les capçaleres són "CODI: descripció"; ens quedem amb el codi.
#  - Els pesos usen coma decimal ("2,87887") -> float.
try:
    df = pd.read_csv(CSV_PATH, sep=";", encoding="utf-8-sig", low_memory=False)
except UnicodeDecodeError:
    df = pd.read_csv(CSV_PATH, sep=";", encoding="latin1", low_memory=False)
df.columns = [c.split(":")[0].strip() for c in df.columns]
for col in (PESO_ESTATAL, PESO_AUTONOMIC):
    df[col] = df[col].astype(str).str.replace(",", ".", regex=False).astype(float)

#Text del CIS -> (codi INE, nom de presentació)
CCAA = {  
    "Andalucía": ("01", "Andalusia"), "Aragón": ("02", "Aragó"),
    "Asturias (Principado de)": ("03", "Astúries"), "Balears (Illes)": ("04", "Illes Balears"),
    "Canarias": ("05", "Canàries"), "Cantabria": ("06", "Cantàbria"),
    "Castilla y León": ("07", "Castella i Lleó"), "Castilla-La Mancha": ("08", "Castella-la Manxa"),
    "Cataluña": ("09", "Catalunya"), "Comunitat Valenciana": ("10", "Comunitat Valenciana"),
    "Extremadura": ("11", "Extremadura"), "Galicia": ("12", "Galícia"),
    "Madrid (Comunidad de)": ("13", "Madrid"), "Murcia (Región de)": ("14", "Múrcia"),
    "Navarra (Comunidad Foral de)": ("15", "Navarra"), "País Vasco": ("16", "País Basc"),
    "Rioja (La)": ("17", "La Rioja"), "Ceuta (Ciudad Autónoma de)": ("18", "Ceuta"),
    "Melilla (Ciudad Autónoma de)": ("19", "Melilla"),
}
desconegudes = set(df["CCAA"].unique()) - set(CCAA)
assert not desconegudes, f"CCAA sense codi INE: {desconegudes}"

#Creacio nova columna COD
df["COD"] = df["CCAA"].map(lambda x: CCAA[x][0])
NOMS = {cod: nom for cod, nom in CCAA.values()}

# 1.2. AGRUPAMENT DE CATEGORIES -------------------------------------------------
# Reduccio de 22 valors de INTENCIONGR a 13 categories amb sentit
NO_EXPRESSA = {"No sabe todavía", "No votaría", "En blanco", "Voto nulo", "N.C."}


def agrupa(valor):
    if valor in COLORS:
        return valor
    if valor in NO_EXPRESSA:
        return "No expressa partit"
    return "Altres partits"


df["PARTIT"] = df["INTENCIONGR"].astype(str).str.strip().map(agrupa)

# 1.3. NORMALITZACIÓ: de recomptes a PERCENTATGES PONDERATS ----------------------
#  Incertesa: mostra efectiva de Kish n_eff = (Σw)² / Σw²  ->  marge d'error al 95%.

#Retorna (taula amb % i marge d'error per partit, n, n_eff, marge d'error màxim)
def estima(g, peso):
    w = g[peso]
    total = w.sum()
    n_eff = total ** 2 / (w ** 2).sum()
    p = w.groupby(g["PARTIT"]).sum() / total                  
    moe_p = 1.96 * (p * (1 - p) / n_eff) ** 0.5 * 100         # marge d'error de cada partit, en punts
    taula = pd.DataFrame({"PCT": p * 100, "MOE_P": moe_p}).reset_index()
    return taula, len(g), n_eff, 1.96 * (0.25 / n_eff) ** 0.5 * 100

#Executacio funcio estima() per a tota Espanya i per cada comunitat.
#Organitza els resultats.
#Retorna un diccionari amb cinc taules, tot el que necessien les figures.
def calcula(base):
    d = df if base == "tots" else df[df["PARTIT"] != "No expressa partit"]
    estatal, n, n_eff, moe = estima(d, PESO_ESTATAL)
    info_estatal = {"NOM": "Tot Espanya", "N": n, "MOE": moe}

    files, info = [], []
    for cod, g in d.groupby("COD"):
        taula, n, n_eff, moe = estima(g, PESO_AUTONOMIC)
        files.append(taula.assign(COD=cod))
        info.append({"COD": cod, "NOM": NOMS[cod], "N": n, "N_EFF": n_eff, "MOE": moe})
    ccaa = pd.concat(files, ignore_index=True)
    info = pd.DataFrame(info).set_index("COD")

    # Guanyador de cada CCAA (només partits reals) + és un EMPAT TÈCNIC?
    # Error de la diferència entre dos percentatges de la mateixa mostra:
    #   SE(p1-p2) = sqrt((p1 + p2 - (p1-p2)²) / n_eff)
    guanyadors = []
    for cod, g in ccaa[ccaa["PARTIT"].isin(PARTITS)].groupby("COD"):
        g = g.sort_values("PCT", ascending=False)
        primer, p1 = g.iloc[0], g.iloc[0]["PCT"] / 100
        p2 = g.iloc[1]["PCT"] / 100 if len(g) > 1 else 0.0
        r = info.loc[cod]
        dif = p1 - p2
        moe_dif = 1.96 * ((p1 + p2 - dif ** 2) / r["N_EFF"]) ** 0.5
        avisos = []
        if r["N"] < MOSTRA_PETITA:
            avisos.append(f"⚠ Mostra molt petita (n={r['N']}): resultat poc fiable")
        if dif < moe_dif:
            avisos.append("≈ Empat tècnic: la diferència és dins del marge d'error")
        guanyadors.append({
            "COD": cod, "NOM": r["NOM"], "PARTIT": primer["PARTIT"], "PCT": primer["PCT"],
            "MARGE": dif * 100, "N": r["N"], "MOE": r["MOE"], "AVIS": "<br>".join(avisos),
        })
    return {"estatal": estatal, "info_estatal": info_estatal, "ccaa": ccaa, "info": info,
            "guanyadors": pd.DataFrame(guanyadors)}


BASES = {"tots": calcula("tots"), "expressat": calcula("expressat")}
Y_COMU = {}
for _b, _d in BASES.items():
    _ok = _d["info"].index[_d["info"]["N"] >= MOSTRA_PETITA]
    _t = _d["ccaa"][_d["ccaa"]["COD"].isin(_ok)]
    Y_COMU[_b] = max((_t["PCT"] + _t["MOE_P"]).max(), (_d["estatal"]["PCT"] + _d["estatal"]["MOE_P"]).max()) * 1.12

# ----------------------------------------------------------------------------
# 2. GEOMETRIES
# ----------------------------------------------------------------------------
if not os.path.exists(GEOJSON_PATH):
    try:
        with urllib.request.urlopen(GEOJSON_URL, timeout=20) as resp, open(GEOJSON_PATH, "wb") as f:
            f.write(resp.read())
    except OSError as e:
        raise SystemExit(f"No s'ha pogut descarregar el mapa. Baixa'l a mà de {GEOJSON_URL} "
                         f"i desa'l com a '{GEOJSON_PATH}'. Detall: {e}")
with open(GEOJSON_PATH, encoding="utf-8") as f:
    GEOJSON = json.load(f)

DX_CAN, DY_CAN = 5.5, 6.5  # Canàries es porta a un requadre sota l'Atlàntic

#Desplaça les coordenades i les arradoneix
def transforma(coords, dx=0.0, dy=0.0):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0] + dx, 3), round(coords[1] + dy, 3)]
    return [transforma(c, dx, dy) for c in coords]


for feat in GEOJSON["features"]:
    dx, dy = (DX_CAN, DY_CAN) if feat["properties"]["cod_ccaa"] == "05" else (0.0, 0.0)
    feat["geometry"]["coordinates"] = transforma(feat["geometry"]["coordinates"], dx, dy)
    feat["properties"] = {"cod_ccaa": feat["properties"]["cod_ccaa"]}  # només ens cal el codi
#Diccionari on la clau -> codi i valor -> forma
#Nomes enviem la forma per resaltar-la
FEATURES = {f["properties"]["cod_ccaa"]: f for f in GEOJSON["features"]}

# Ceuta i Melilla: massa petites per clicar-hi -> addicio cercle
MARCADORS = {"18": (-5.31, 35.89), "19": (-2.94, 35.29)} 

# ----------------------------------------------------------------------------
# 3. FIGURES
# ----------------------------------------------------------------------------
#Plantilla text surt en passar el ratolí
HOVER = ("<b>%{customdata[1]}</b><br>Més votat: %{customdata[2]} (%{customdata[3]:.1f}%)<br>"
         "Avantatge sobre el 2n: %{customdata[4]:.1f} punts<br>"
         "Mostra: %{customdata[5]} persones · marge d'error ±%{customdata[6]:.1f} punts<br>"
         "%{customdata[7]}<extra></extra>")
COLS_HOVER = ["COD", "NOM", "PARTIT", "PCT", "MARGE", "N", "MOE", "AVIS"]

#Parametres:
#   sel: codi comunitat seleccionada o "ESP"
#   base: "tots" o "expressat"
#Retorna: figura del mapa
def figura_mapa(sel, base):
    g = BASES[base]["guanyadors"].reset_index(drop=True)
    presents = [p for p in PARTITS if p in set(g["PARTIT"])]
    n = len(presents)
    idx = {p: i for i, p in enumerate(presents)}

    # Cada partit ocupa un tram [i, i+1) de l'escala.
    #   Dins del tram, la posició fraccionària és l'avantatge -> més intens = més avantatge.
    z = [idx[p] + 0.999 * min(m, CAP_AVANTATGE) / CAP_AVANTATGE for p, m in zip(g["PARTIT"], g["MARGE"])]
    escala = []
    for p, i in idx.items():
        escala += [[i / n, mescla(COLORS[p], T_MIN)], [(i + 1) / n - 1e-6, COLORS[p]]]
    escala.append([1.0, COLORS[presents[-1]]])

    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=GEOJSON, featureidkey="properties.cod_ccaa", locations=g["COD"], z=z,
        zmin=0, zmax=n, colorscale=escala, showscale=False,
        marker_line_color="white", marker_line_width=0.8,
        customdata=g[COLS_HOVER].values, hovertemplate=HOVER, showlegend=False))

    # Llegenda: una entrada per partit guanyador (color de MÀXIMA intensitat).
    for p in presents:
        fig.add_trace(go.Scattergeo(lon=[None], lat=[None], mode="markers", name=p, hoverinfo="skip",
                                    marker=dict(size=11, symbol="square", color=COLORS[p])))

    # Color real de cada comunitat (partit + intensitat), per als marcadors de Ceuta i Melilla
    fons = {r.COD: mescla(COLORS[r.PARTIT], intensitat(r.MARGE)) for r in g.itertuples()}
    # Ceuta i Melilla: marcador clicable amb el color de la comunitat
    mk = g[g["COD"].isin(MARCADORS)]
    fig.add_trace(go.Scattergeo(
        lon=[MARCADORS[c][0] for c in mk["COD"]], lat=[MARCADORS[c][1] for c in mk["COD"]],
        mode="markers+text", text=mk["NOM"], textposition="bottom center", textfont_size=10,
        marker=dict(size=13, color=[fons[c] for c in mk["COD"]], line=dict(color="white", width=1.5)),
        customdata=mk[COLS_HOVER].values, hovertemplate=HOVER, showlegend=False))

    # Marc i nom del requadre de Canàries
    x0, x1, y0, y1 = -18.5 + DX_CAN, -13.0 + DX_CAN, 27.4 + DY_CAN, 29.7 + DY_CAN
    fig.add_trace(go.Scattergeo(
        lon=[x0, x1, x1, x0, x0, x0], lat=[y0, y0, y1, y1, y0, y0], mode="lines",
        line=dict(color="#AAAAAA", width=1, dash="dot"), hoverinfo="skip", showlegend=False))

    # Ressaltat de la CCAA seleccionada: contorn negre..
    if sel != TOT_ESP:
        fig.add_trace(go.Choropleth(
            geojson={"type": "FeatureCollection", "features": [FEATURES[sel]]},
            featureidkey="properties.cod_ccaa", locations=[sel], z=[1],
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
            marker_line_color="#111111", marker_line_width=3, hoverinfo="skip", showlegend=False))
        if sel in MARCADORS:
            fig.add_trace(go.Scattergeo(
                lon=[MARCADORS[sel][0]], lat=[MARCADORS[sel][1]], mode="markers",
                marker=dict(size=22, symbol="circle-open", line=dict(color="#111111", width=3)),
                hoverinfo="skip", showlegend=False))

    fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
    fig.update_layout(
        margin=dict(r=0, t=0, l=0, b=55), height=560, paper_bgcolor="white",
        legend=dict(orientation="h", x=0.5, xanchor="center", y=0, yanchor="top", title_text="",
                    font_size=13, itemclick=False, itemdoubleclick=False),
        uirevision="mapa", clickmode="event")
    return fig

#Barres del territori triat
def figura_barres(cod, base):
    d = BASES[base]
    if cod == TOT_ESP:
        taula = d["estatal"]                          # vista general
    else:
        taula = d["ccaa"][d["ccaa"]["COD"] == cod]    # una comunitat concreta
    taula = taula[taula["PCT"] > 0]
    #Ordenació lògica (valor descendent) ; Categories residuals sempre al final.
    principals = taula[~taula["PARTIT"].isin(RESIDUALS)].sort_values("PCT", ascending=False)
    residuals = taula[taula["PARTIT"].isin(RESIDUALS)].sort_values("PCT", ascending=False)
    taula = pd.concat([principals, residuals])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=taula["PARTIT"], y=taula["PCT"], marker_color=[COLORS[p] for p in taula["PARTIT"]],
        error_y=dict(type="data", array=taula["MOE_P"], color="#444", thickness=1.2, width=4),
        customdata=taula["MOE_P"],
        hovertemplate="%{x}: %{y:.1f}% (±%{customdata:.1f} punts)<extra></extra>"))
    
    #Numero va sobre la barra d'error
    fig.add_trace(go.Scatter(
        x=taula["PARTIT"], y=taula["PCT"] + taula["MOE_P"], mode="text",
        text=taula["PCT"].map(lambda v: f"{v:.1f}%"), textposition="top center",
        hoverinfo="skip"))
    
    #Escala eix Y
    y_max = max(Y_COMU[base], (taula["PCT"] + taula["MOE_P"]).max() * 1.12)

    fig.update_layout(
        height=540, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white", bargap=0.3,
        showlegend=False,  # sense llegenda: cada barra ja porta el nom del partit a l'eix
        xaxis=dict(title="Partit", showgrid=False, ticks="", tickangle=-35, automargin=True,
                   categoryorder="array", categoryarray=list(taula["PARTIT"])),
        yaxis=dict(range=[0, y_max], title=TITOL_Y[base], ticksuffix="%", gridcolor="#EEEEEE", zeroline=False))
    return fig


# ----------------------------------------------------------------------------------------------
# 4. LAYOUT
# Dos tipus de peces:
#   html. -> etiques pagina web normal: Div(caixa), H1/H3(titols), P(paragraf), Label(etiquetes)
#   dcc. -> Dash Core Components: peces interactives -> Graph, RadioItems, Dropdown
# ----------------------------------------------------------------------------------------------
N_CEUTA = int((df["COD"] == "18").sum())
N_MELILLA = int((df["COD"] == "19").sum())
FONT = {"fontFamily": "Arial, sans-serif"}

app = Dash(__name__) #Creacio aplicacio
app.title = "Intenció directa de vot · CIS 3577"

#Opcions del desplegable (ordre alfabètic)
opcions_ccaa = [{"label": "Tot Espanya", "value": TOT_ESP}] + sorted(
    ({"label": n, "value": c} for c, n in NOMS.items()), key=lambda o: o["label"])

app.layout = html.Div(style={**FONT, "maxWidth": "1300px", "margin": "0 auto", "padding": "10px 20px"}, children=[
    # ---- Capçalera: es llegeix en 5 segons ----
    html.H1("Intenció directa de vot a Espanya", style={"textAlign": "center", "marginBottom": 0}),
    html.P("Baròmetre CIS 3577 · Setembre 2026",
           style={"textAlign": "center", "color": "#666", "marginTop": 4, "marginBottom": 4}),

    # ---- Franja de TOT ESPANYA: sempre estatal, no depèn del territori triat a sota ----
    html.Div(style={"background": "#F3F3F3", "borderRadius": "10px", "padding": "12px 14px", "marginTop": 8}, children=[
        html.Div(id="kpis-titol", style={"fontWeight": "bold", "marginBottom": 8}),
        html.Div(id="kpis", style={"display": "flex", "gap": "12px"}),
        html.Div(style={"marginTop": 10}, children=[  # Reconfigurar
            html.Label("Percentatge:", style={"fontWeight": "bold", "marginRight": 8}),
            dcc.RadioItems(id="base", value="tots", inline=True, inputStyle={"marginLeft": 12, "marginRight": 4},
                           options=[{"label": etiq, "value": clau} for clau, etiq in BASES_ETIQ.items()]),
        ]),
    ]),

    # ---- Detall per territori ----
    html.H2("Detall per territori", style={"marginTop": 26, "marginBottom": 6}),
    html.Div(style={"display": "flex", "gap": "12px", "alignItems": "center", "flexWrap": "wrap"}, children=[
        html.Label("Clica una comunitat al mapa o tria-la aquí:", style={"fontWeight": "bold"}),  # Filtrar
        dcc.Dropdown(id="ccaa-dd", options=opcions_ccaa, value=CCAA_INICIAL, clearable=False, style={"width": "240px"}),
        html.Button("↺ Restableix la vista", id="reset", n_clicks=0,
                    title="Torna a Tot Espanya i a la base «sobre el cens»",
                    style={"padding": "7px 12px", "border": "1px solid #999", "borderRadius": "6px",
                           "background": "white", "cursor": "pointer", "fontSize": 14}),
    ]),

    html.Div(style={"display": "flex", "gap": "20px", "marginTop": "10px"}, children=[
        html.Div(style={"width": "58%"}, children=[
            html.H3("Partit més votat a cada comunitat"),
            html.P("Color més intens = més avantatge sobre el segon partit; color pàl·lid = resultat ajustat. ",
                   style={"color": "#666", "marginTop": -8, "fontSize": 13}),
            dcc.Graph(id="mapa", config={"displayModeBar": False}),
        ]),
        html.Div(style={"width": "42%"}, children=[
            html.H3(id="titol"),
            html.P(id="subtitol", style={"color": "#666", "marginTop": -8}),
            dcc.Graph(id="barres", config={"displayModeBar": False}),
        ]),
    ]),

    html.Div(style={"fontSize": 12, "color": "#777", "marginTop": 14, "lineHeight": 1.5}, children=[
        html.P("Dades: intenció directa de vot de les microdades del baròmetre CIS 3577 (enquesta telefònica, "
               f"{DATES_CAMP}, població espanyola de 18 anys o més). «Sobre el cens» equival al «% sobre censo» de la taula oficial del CIS. "
               "Ponderació: PESO per a Espanya i PESOCCAA per a cada comunitat, segons la fitxa tècnica."),
        html.P("Incertesa: les barres d'error són l'interval de confiança al 95% calculat amb la mostra efectiva de "
               "Kish; per això són una mica més amples que els marges que publica el CIS, que suposen mostreig "
               "aleatori simple. «Empat tècnic» vol dir que la diferència entre els dos primers és dins del marge "
               f"d'error. Ceuta i Melilla tenen només {N_CEUTA} i {N_MELILLA} entrevistes. Canàries apareix "
               "reubicada al requadre. Tot Espanya usa PESO i cada comunitat PESOCCAA (ponderacions diferents), "
               "per això no es compara una comunitat amb la mitjana estatal."),
        html.P("Font: Centro de Investigaciones Sociológicas (CIS), estudi 3577, microdades. "
               "Mapa: click_that_hood (GeoJSON de comunitats autònomes)."),
    ]),
])

# ----------------------------------------------------------------------------
# 5. CALLBACKS
# ----------------------------------------------------------------------------
PRINCIPALS_KPI = ["PSOE", "PP", "VOX", "Sumar", "Podemos"]

def targeta(nom, valor, color):
    return html.Div([html.Div(nom, style={"fontSize": 15}),
                     html.Div(f"{valor:.1f}%", style={"fontSize": 30, "fontWeight": "bold"})],
                    style={"flex": 1, "padding": "10px", "borderRadius": "8px", "textAlign": "center",
                           "backgroundColor": color, "color": text_sobre(color)})

#Depen de la base de càlcul ("tots" o "expressat")
@app.callback([Output("kpis", "children"), Output("kpis-titol", "children")], Input("base", "value"))
def actualitza_kpis(base):
    nac = BASES[base]["estatal"].set_index("PARTIT")["PCT"]
    cards = [targeta(p, nac.get(p, 0), COLORS[p]) for p in PRINCIPALS_KPI]
    extra = "No expressa partit" if base == "tots" else "Altres partits"
    cards.append(targeta(extra, nac.get(extra, 0), COLORS[extra]))
    return cards, f"TOT ESPANYA · {BASES_ETIQ[base]}"

#Un unic callback sincronitza el mapa, desplegable i barres
#Entrades:
#   mapa.clickData: ultim clic al mapa
#   ccaa--dd.value: desplegable
#   base.value: els botos
#Sortides (que acutalitza):
#   ccaa-dd.value: el desplegable
#   titol.children: titol
#   subtitol.children: subtitol
#   barres.figure: grafic de barres
#   mapa.figure: el mapa
@app.callback(
    [Output("ccaa-dd", "value"), Output("titol", "children"), Output("subtitol", "children"),
     Output("barres", "figure"), Output("mapa", "figure"), Output("base", "value"), Output("mapa", "clickData")],
    [Input("mapa", "clickData"), Input("ccaa-dd", "value"), Input("base", "value"), Input("reset", "n_clicks")],
)
def actualitza_vista(click, dropdown, base, _n_reset):
    sel = dropdown
    if ctx.triggered_id == "mapa" and click:
        sel = click["points"][0]["customdata"][0]  # primer camp = codi INE (també per als marcadors)
    if ctx.triggered_id == "reset":                # botó «Restableix la vista»: valors per defecte
        sel, base = TOT_ESP, "tots"
    info = BASES[base]["info_estatal"] if sel == TOT_ESP else BASES[base]["info"].loc[sel]
    unitat = "entrevistes" if base == "tots" else "persones que declaren partit"
    sub = (f"{info['N']} {unitat} · marge d'error màxim ±{info['MOE']:.1f} punts"
           + (" · ⚠ mostra molt petita" if info["N"] < MOSTRA_PETITA else ""))
    # L'últim valor (None) buida el clic: així es pot tornar a clicar la mateixa comunitat i torna a disparar-se
    return sel, f"Intenció de vot: {info['NOM']}", sub, figura_barres(sel, base), figura_mapa(sel, base), base, None


if __name__ == "__main__":
    app.run(debug=False)
