import streamlit as st
import pandas as pd
from datetime import datetime
import os
import folium
from streamlit_folium import st_folium
from folium.plugins import LocateControl
import requests
import json

# --- 設定 ---
DATA_FILE = 'moth_data.csv'

# オフライン用地図・データ設定
OFFLINE_MAP_IMAGE = 'offline_map.png' 
OFFLINE_GEOJSON = 'offline_map.geojson'       # 手動配置用（国境など）
OFFLINE_ROADS = 'offline_roads.geojson'       # アプリでダウンロードする詳細道路データ

# Overpass APIのエンドポイント
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# --- ページ設定 ---
st.set_page_config(page_title="学内蛾類調査マップ Pro", page_icon="🦋", layout="wide")

# --- 関数: データのキャッシュ読み込み ---
@st.cache_data
def load_road_geojson():
    """道路データをキャッシュして読み込む（リロードごとのファイルI/Oを回避）"""
    if os.path.exists(OFFLINE_ROADS):
        try:
            with open(OFFLINE_ROADS, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            return pd.read_csv(DATA_FILE)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])
    else:
        return pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])

def append_data(new_record):
    df = load_data()
    new_df = pd.DataFrame([new_record])
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)
    return df

def save_dataframe(df):
    df.to_csv(DATA_FILE, index=False)

# --- 関数: 道路データのダウンロード ---
def download_roads_for_bounds(south, west, north, east):
    query = f"""
    [out:json][timeout:25];
    (
      way["highway"]({south},{west},{north},{east});
    );
    out geom;
    """
    try:
        response = requests.get(OVERPASS_URL, params={'data': query})
        response.raise_for_status()
        data = response.json()
        
        features = []
        for element in data.get('elements', []):
            if element['type'] == 'way' and 'geometry' in element:
                coords = [[pt['lon'], pt['lat']] for pt in element['geometry']]
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": element.get('tags', {})
                }
                features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        if not features:
            return False, "指定範囲内に道路データが見つかりませんでした。"
            
        with open(OFFLINE_ROADS, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, ensure_ascii=False)
        
        # キャッシュをクリアして再読み込みさせる
        load_road_geojson.clear()
            
        return True, f"{len(features)} 本の道路データをダウンロードしました。"
        
    except Exception as e:
        return False, f"エラーが発生しました: {e}"

# --- タイトル ---
st.title("🦋 学内蛾類調査フィールドノート (Fixed)")

# --- ローカル保存場所の表示 ---
current_dir = os.getcwd()
st.caption(f"📂 Data Path: `{os.path.join(current_dir, DATA_FILE)}`")

# --- セッション状態の初期化 ---
if 'selected_lat' not in st.session_state:
    df_init = load_data()
    if not df_init.empty:
        last_rec = df_init.iloc[-1]
        st.session_state.selected_lat = last_rec['lat']
        st.session_state.selected_lon = last_rec['lon']
    else:
        st.session_state.selected_lat = 35.6895
        st.session_state.selected_lon = 139.6917

# ウィジェット用の初期値も確実にセットする
if 'input_lat' not in st.session_state:
    st.session_state.input_lat = st.session_state.selected_lat
if 'input_lon' not in st.session_state:
    st.session_state.input_lon = st.session_state.selected_lon

if 'last_collector' not in st.session_state:
    st.session_state.last_collector = "M. Yamaguchi"

if 'map_bounds' not in st.session_state:
    st.session_state.map_bounds = None

if 'img_bounds' not in st.session_state:
    st.session_state.img_bounds = [35.6890, 139.6910, 35.6900, 139.6925]

# --- 緯度経度フォームのコールバック関数 ---
def update_map_from_input():
    st.session_state.selected_lat = st.session_state.input_lat
    st.session_state.selected_lon = st.session_state.input_lon

# --- レイアウト ---
col1, col2 = st.columns([1, 2])

# --- 右カラム：地図 ---
with col2:
    st.subheader("🗺️ 位置決め")
    
    # 地図タイルの選択肢
    map_options = [
        "OpenStreetMap (Online)", 
        "地理院地図 標準 (Online)", 
        "地理院地図 写真 (Online)", 
        "Offline Image (PNG/SVG)", 
        "White Map (Simple)"
    ]
    tile_option = st.radio("地図モード", map_options, index=0, horizontal=True)

    # --- 高速化のための追跡モード切り替え ---
    enable_bounds_tracking = st.checkbox("📡 地図範囲を追跡する（道路ダウンロード時のみONにしてください）", value=False)
    
    # 道路データの表示制御
    show_roads = False
    road_data = load_road_geojson() # キャッシュからロード
    
    # データが存在する場合のみチェックボックスを表示
    if road_data:
        show_roads = st.checkbox("🛣️ 道路データを表示", value=True)
    else:
        st.caption("※道路データは未ダウンロードです")

    # --- データ取得・削除ツール ---
    with st.expander("📥 道路データの管理 (ダウンロード・削除)", expanded=True):
        # 1. ダウンロード機能
        if enable_bounds_tracking:
            st.info("地図を拡大してボタンを押してください。")
            if st.button("現在範囲の道路データをダウンロード"):
                if st.session_state.map_bounds:
                    b = st.session_state.map_bounds
                    south, west = b['_southWest']['lat'], b['_southWest']['lng']
                    north, east = b['_northEast']['lat'], b['_northEast']['lng']
                    
                    lat_diff = abs(north - south)
                    lon_diff = abs(east - west)
                    
                    if lat_diff > 0.5 or lon_diff > 0.5:
                        st.error("範囲が広すぎます。ズームインしてください。")
                    else:
                        with st.spinner("道路データを取得中..."):
                            success, msg = download_roads_for_bounds(south, west, north, east)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                else:
                    st.warning("範囲情報がまだありません。地図を少し動かしてください。")
        else:
            st.caption("ダウンロードするには「地図範囲を追跡する」をONにしてください。")

        # 2. 削除機能 (軽量化)
        if road_data: 
            st.markdown("---")
            if st.button("🗑️ ダウンロードした道路データを削除 (軽量化)"):
                try:
                    if os.path.exists(OFFLINE_ROADS):
                        os.remove(OFFLINE_ROADS)
                        load_road_geojson.clear() # キャッシュをクリア
                        st.success("削除しました。動作が軽くなります。")
                        st.rerun()
                except Exception as e:
                    st.error(f"削除に失敗しました: {e}")

    # --- 地図の生成 ---
    m = None
    if tile_option == "地理院地図 標準 (Online)":
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=18,
            tiles='https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png',
            attr='国土地理院',
            prefer_canvas=True
        )
    elif tile_option == "地理院地図 写真 (Online)":
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=18,
            tiles='https://cyberjapandata.gsi.go.jp/xyz/ort/{z}/{x}/{y}.jpg',
            attr='国土地理院',
            prefer_canvas=True
        )
    elif tile_option == "Offline Image (PNG/SVG)":
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=18,
            tiles=None,
            prefer_canvas=True
        )
        if os.path.exists(OFFLINE_MAP_IMAGE):
            bounds = [
                [st.session_state.img_bounds[0], st.session_state.img_bounds[1]], 
                [st.session_state.img_bounds[2], st.session_state.img_bounds[3]]
            ]
            folium.raster_layers.ImageOverlay(
                name="Offline Image Map",
                image=OFFLINE_MAP_IMAGE,
                bounds=bounds,
                opacity=1.0,
                interactive=True,
                cross_origin=False,
                zindex=1,
            ).add_to(m)
        else:
            folium.LatLngPopup().add_to(m)
    elif tile_option == "White Map (Simple)":
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=15,
            tiles=None,
            prefer_canvas=True
        )
        folium.LatLngPopup().add_to(m)
    else:
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=18,
            prefer_canvas=True
        )

    # --- 道路データのオーバーレイ ---
    if show_roads and road_data:
        folium.GeoJson(
            road_data,
            name="Roads",
            style_function=lambda x: {
                'color': '#FFA500', 
                'weight': 2,
                'opacity': 0.8
            },
            smooth_factor=2.0,
            interactive=False 
        ).add_to(m)

    # --- 共通コントロール ---
    LocateControl(auto_start=False).add_to(m)

    # データプロット
    df = load_data()
    for index, row in df.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=6,
            color="#FF007F",
            fill=True,
            fill_color="#FF007F",
            fill_opacity=0.7,
            popup=f"{row['種名']} ({row['日付']})",
            tooltip=row['種名']
        ).add_to(m)

    folium.Marker(
        [st.session_state.selected_lat, st.session_state.selected_lon],
        popup="ここを記録します",
        icon=folium.Icon(color='red')
    ).add_to(m)

    # --- イベント設定 ---
    ret_objs = ["last_clicked"]
    if enable_bounds_tracking:
        ret_objs.append("bounds")

    map_data = st_folium(
        m, 
        height=500, 
        width="100%", 
        returned_objects=ret_objs
    )

    if map_data:
        if enable_bounds_tracking and map_data.get("bounds"):
            st.session_state.map_bounds = map_data["bounds"]

        if map_data.get("last_clicked"):
            clicked_lat = map_data["last_clicked"]["lat"]
            clicked_lon = map_data["last_clicked"]["lng"]
            
            if (clicked_lat != st.session_state.selected_lat or 
                clicked_lon != st.session_state.selected_lon):
                
                st.session_state.selected_lat = clicked_lat
                st.session_state.selected_lon = clicked_lon
                st.session_state.input_lat = clicked_lat
                st.session_state.input_lon = clicked_lon
                st.rerun()

# --- 左カラム：入力フォーム ---
with col1:
    st.subheader("📝 記録データ")
    
    st.markdown("**📍 位置情報**")
    
    # 修正箇所: value引数を削除し、keyだけで管理するように変更
    lat = st.number_input(
        "緯度", 
        format="%.6f", 
        key="input_lat",
        on_change=update_map_from_input
    )
    lon = st.number_input(
        "経度", 
        format="%.6f", 
        key="input_lon",
        on_change=update_map_from_input
    )
    
    st.markdown("---")
    
    with st.form("survey_form", clear_on_submit=True):
        now = datetime.now()
        input_date = st.date_input("日付", now)
        input_time = st.time_input("時間", now)
        
        species_name = st.text_input("種名 (標準和名)", placeholder="例: オオミズアオ")
        
        collection_method = st.selectbox(
            "採集・確認方法",
            ["Light trap (灯火採集)", "Net sweeping (ネット)", "Finding (見取り)", "Bait trap (ベイト)"]
        )
        
        collector = st.text_input("採集者", value=st.session_state.last_collector)
        
        notes = st.text_area("備考", placeholder="環境など")
        
        submitted = st.form_submit_button("💾 記録を保存する")

        if submitted:
            if species_name:
                st.session_state.last_collector = collector
                new_record = {
                    "日付": input_date,
                    "時間": input_time,
                    "lat": lat,
                    "lon": lon,
                    "種名": species_name,
                    "方法": collection_method,
                    "採集者": collector,
                    "備考": notes
                }
                append_data(new_record)
                st.success(f"保存完了: {species_name}")
            else:
                st.error("種名を入力してください。")

    st.markdown("---")
    with st.expander("🛠️ データの編集・削除"):
        st.info("編集後は「変更を適用して保存」を押してください。")
        current_df = load_data()
        edited_df = st.data_editor(
            current_df,
            num_rows="dynamic",
            use_container_width=True,
            key="data_editor"
        )
        if st.button("⚠️ 変更を適用して保存"):
            save_dataframe(edited_df)
            st.success("データを更新しました！")
            st.rerun()

        csv_data = current_df.to_csv(index=False).encode('utf-8_sig')
        st.download_button("CSVコピーを作成 (Download)", csv_data, "moth_data_export.csv", "text/csv")
