import streamlit as st
import pandas as pd
from datetime import datetime
import os
import folium
from streamlit_folium import st_folium
from folium.plugins import LocateControl, Geocoder
import requests
import json
import glob

# --- ページ設定 ---
st.set_page_config(page_title="学内蛾類調査マップ Pro", page_icon="🦋", layout="wide")

# ==========================================
# 🔧 定数・関数定義 (Function Definitions)
# ==========================================

FILE_PREFIX = "moth_data_"
OFFLINE_MAP_IMAGE = 'offline_map.png' 
OFFLINE_GEOJSON = 'offline_map.geojson'
OFFLINE_ROADS = 'offline_roads.geojson'
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# 採集方法の定義
METHODS = ["Light trap (灯火採集)", "Net sweeping (ネット)", "Finding (見取り)", "Bait trap (ベイト)"]

def get_existing_projects():
    files = glob.glob(f"{FILE_PREFIX}*.csv")
    projects = [os.path.basename(f).replace(FILE_PREFIX, "").replace(".csv", "") for f in files]
    if not projects:
        return ["default"]
    return sorted(projects)

@st.cache_data
def load_road_geojson():
    if os.path.exists(OFFLINE_ROADS):
        try:
            with open(OFFLINE_ROADS, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None

def load_data(file_path):
    """指定されたパスのCSVデータを読み込む"""
    if os.path.exists(file_path):
        try:
            return pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])
    else:
        return pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])

def append_data(file_path, new_record):
    """新しい1行を追加して保存"""
    df = load_data(file_path)
    new_df = pd.DataFrame([new_record])
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(file_path, index=False)
    return df

def save_dataframe(file_path, df):
    """データフレーム全体を上書き保存"""
    df.to_csv(file_path, index=False)

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
        
        load_road_geojson.clear()
        return True, f"{len(features)} 本の道路データをダウンロードしました。"
        
    except Exception as e:
        return False, f"エラーが発生しました: {e}"


# ==========================================
# 📁 プロジェクト管理機能 (サイドバー)
# ==========================================
st.sidebar.title("📁 プロジェクト管理")

existing_projects = get_existing_projects()
if 'current_project' not in st.session_state:
    st.session_state.current_project = existing_projects[0]

try:
    current_index = existing_projects.index(st.session_state.current_project)
except ValueError:
    current_index = 0

selected_project = st.sidebar.selectbox(
    "プロジェクトを選択", 
    existing_projects, 
    index=current_index
)
st.session_state.current_project = selected_project

with st.sidebar.expander("➕ 新規プロジェクト作成"):
    new_proj_name = st.text_input("プロジェクト名 (例: 2025_Summer)", placeholder="半角英数推奨")
    if st.button("作成"):
        if new_proj_name and new_proj_name not in existing_projects:
            st.session_state.current_project = new_proj_name
            new_filename = f"{FILE_PREFIX}{new_proj_name}.csv"
            empty_df = pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])
            empty_df.to_csv(new_filename, index=False)
            st.success(f"プロジェクト「{new_proj_name}」を作成しました！")
            st.rerun()
        elif new_proj_name in existing_projects:
            st.error("その名前は既に存在します。")
        else:
            st.error("名前を入力してください。")

# 現在のデータファイルパスを決定
DATA_FILE = f"{FILE_PREFIX}{st.session_state.current_project}.csv"
st.sidebar.info(f"現在のデータ: `{DATA_FILE}`")

# --- 💾 バックアップと復元・結合機能 ---
st.sidebar.markdown("---")
st.sidebar.subheader("💾 バックアップと復元")

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "rb") as f:
        csv_bytes = f.read()
    st.sidebar.download_button(
        label="📥 現在のデータをDL (Backup)",
        data=csv_bytes,
        file_name=f"{st.session_state.current_project}_backup_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        help="プロジェクトごとのCSVデータを手元に保存します。"
    )
else:
    st.sidebar.warning("データファイルがまだありません。")

uploaded_file = st.sidebar.file_uploader("📤 CSVを読み込み (復元/追加)", type=["csv"], help="バックアップしたCSVを読み込み、現在のプロジェクトに上書き、または追加します。")

if uploaded_file is not None:
    try:
        import_df = pd.read_csv(uploaded_file)
        required_cols = ["日付", "時間", "lat", "lon", "種名"]
        
        # カラムチェック
        if all(col in import_df.columns for col in required_cols):
            st.sidebar.info(f"読み込み成功: {len(import_df)} 件のデータ")
            
            col1, col2 = st.sidebar.columns(2)
            
            # 追加 (Merge) ボタン
            if col1.button("➕ 既存データに追加"):
                current_df = load_data(DATA_FILE)
                merged_df = pd.concat([current_df, import_df], ignore_index=True)
                save_dataframe(DATA_FILE, merged_df)
                st.sidebar.success(f"{len(import_df)} 件を追加しました！")
                st.rerun()
                
            # 上書き (Overwrite) ボタン
            if col2.button("⚠️ 上書きして復元"):
                save_dataframe(DATA_FILE, import_df)
                st.sidebar.warning("データを完全に置き換えました。")
                st.rerun()
        else:
            st.sidebar.error("エラー: CSVの形式が異なります（必要な列が見つかりません）。")
    except Exception as e:
        st.sidebar.error(f"読み込みエラー: {e}")

st.sidebar.markdown("---")


# ==========================================
# 🗺️ メインアプリケーション
# ==========================================

# --- タイトル ---
st.title("🦋 学内蛾類調査フィールドノート (Merge Function)")
st.caption(f"Project: **{st.session_state.current_project}**")

# --- セッション状態の初期化 ---
if 'selected_lat' not in st.session_state:
    df_init = load_data(DATA_FILE)
    if not df_init.empty:
        # 有効な座標がある最後のデータを検索
        valid_df = df_init.dropna(subset=['lat', 'lon'])
        if not valid_df.empty:
            last_rec = valid_df.iloc[-1]
            st.session_state.selected_lat = last_rec['lat']
            st.session_state.selected_lon = last_rec['lon']
        else:
            st.session_state.selected_lat = 35.6895
            st.session_state.selected_lon = 139.6917
    else:
        st.session_state.selected_lat = 35.6895
        st.session_state.selected_lon = 139.6917

# ガード
if not st.session_state.selected_lat or st.session_state.selected_lat == 0:
    st.session_state.selected_lat = 35.6895
if not st.session_state.selected_lon or st.session_state.selected_lon == 0:
    st.session_state.selected_lon = 139.6917

if 'input_lat' not in st.session_state:
    st.session_state.input_lat = st.session_state.selected_lat
if 'input_lon' not in st.session_state:
    st.session_state.input_lon = st.session_state.selected_lon

# --- 共通入力情報の保持 ---
if 'last_collector' not in st.session_state:
    st.session_state.last_collector = "M. Yamaguchi"
if 'last_method_index' not in st.session_state:
    st.session_state.last_method_index = 0
if 'last_notes' not in st.session_state:
    st.session_state.last_notes = ""

if 'last_date' not in st.session_state:
    st.session_state.last_date = datetime.now()
if 'last_time' not in st.session_state:
    st.session_state.last_time = datetime.now()

if 'map_bounds' not in st.session_state:
    st.session_state.map_bounds = None

if 'img_bounds' not in st.session_state:
    st.session_state.img_bounds = [35.6890, 139.6910, 35.6900, 139.6925]

def update_form_coords():
    st.session_state.selected_lat = st.session_state.input_lat
    st.session_state.selected_lon = st.session_state.input_lon

# --- レイアウト ---
col_map, col_form = st.columns([2, 1])

# --- カラム1（左・上）：地図 ---
with col_map:
    st.subheader("🗺️ 位置決め")
    st.info("👆 **地図上をタップ（クリック）** すると、その場所にピンが移動し座標が確定します。移動中はリロードされません。")
    
    map_options = [
        "OpenStreetMap (Online)", 
        "地理院地図 標準 (Online)", 
        "地理院地図 写真 (Online)", 
        "Offline Image (PNG/SVG)", 
        "White Map (Simple)"
    ]
    tile_option = st.radio("地図モード", map_options, index=0, horizontal=True)

    enable_bounds_tracking = st.checkbox("📡 地図範囲を追跡する（道路ダウンロード時のみONにしてください）", value=False)
    
    show_roads = False
    road_data = load_road_geojson()
    if road_data:
        show_roads = st.checkbox("🛣️ 道路データを表示", value=True)
    else:
        st.caption("※道路データは未ダウンロードです")

    with st.expander("📥 道路データの管理 (ダウンロード・削除)", expanded=False):
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

        if road_data: 
            st.markdown("---")
            if st.button("🗑️ ダウンロードした道路データを削除 (軽量化)"):
                try:
                    if os.path.exists(OFFLINE_ROADS):
                        os.remove(OFFLINE_ROADS)
                        load_road_geojson.clear()
                        st.success("削除しました。動作が軽くなります。")
                        st.rerun()
                except Exception as e:
                    st.error(f"削除に失敗しました: {e}")

    # 地図の生成
    m = None
    center_lat = st.session_state.selected_lat
    center_lon = st.session_state.selected_lon
    
    if tile_option == "地理院地図 標準 (Online)":
        m = folium.Map(
            location=[center_lat, center_lon], 
            zoom_start=18,
            tiles='https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png',
            attr='国土地理院',
            prefer_canvas=True
        )
    elif tile_option == "地理院地図 写真 (Online)":
        m = folium.Map(
            location=[center_lat, center_lon], 
            zoom_start=18,
            tiles='https://cyberjapandata.gsi.go.jp/xyz/ort/{z}/{x}/{y}.jpg',
            attr='国土地理院',
            prefer_canvas=True
        )
    elif tile_option == "Offline Image (PNG/SVG)":
        m = folium.Map(
            location=[center_lat, center_lon], 
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
            location=[center_lat, center_lon], 
            zoom_start=15,
            tiles=None,
            prefer_canvas=True
        )
        folium.LatLngPopup().add_to(m)
    else:
        m = folium.Map(
            location=[center_lat, center_lon], 
            zoom_start=18,
            prefer_canvas=True
        )

    Geocoder(add_marker=False).add_to(m)

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

    LocateControl(
        auto_start=False,
        strings={"title": "現在地へ移動"}
    ).add_to(m)

    # --- 修正: データ読み込み時にNaNを除外 ---
    df = load_data(DATA_FILE)
    # 緯度・経度が数値でない、またはNaNの行を除外する
    df_clean = df.dropna(subset=['lat', 'lon'])
    
    for index, row in df_clean.iterrows():
        #念のためさらにtry-exceptで囲む
        try:
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
        except Exception:
            continue

    folium.Marker(
        [st.session_state.selected_lat, st.session_state.selected_lon],
        popup="選択地点",
        icon=folium.Icon(color='red', icon='info-sign')
    ).add_to(m)

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
            
            if clicked_lat != 0 and clicked_lon != 0:
                if (abs(clicked_lat - st.session_state.selected_lat) > 0.000001 or 
                    abs(clicked_lon - st.session_state.selected_lon) > 0.000001):
                    
                    st.session_state.selected_lat = clicked_lat
                    st.session_state.selected_lon = clicked_lon
                    st.session_state.input_lat = clicked_lat
                    st.session_state.input_lon = clicked_lon
                    st.rerun()

# --- カラム2（右・下）：入力フォーム ---
with col_form:
    
    st.subheader("🚀 リアルタイム記録")
    
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("緯度", format="%.6f", key="input_lat", on_change=update_form_coords)
    with c2:
        st.number_input("経度", format="%.6f", key="input_lon", on_change=update_form_coords)

    with st.form("quick_record_form", clear_on_submit=True):
        quick_species = st.text_input("種名 (入力してEnter)", placeholder="例: オオミズアオ")
        quick_submit = st.form_submit_button("今すぐ記録する")
        
        if quick_submit:
            if quick_species:
                now_quick = datetime.now()
                
                current_collector = st.session_state.last_collector
                try:
                    current_method = METHODS[st.session_state.last_method_index]
                except:
                    current_method = METHODS[0]
                current_notes = st.session_state.last_notes
                
                rec_lat = st.session_state.selected_lat
                rec_lon = st.session_state.selected_lon
                
                if not rec_lat or rec_lat == 0:
                    rec_lat = 35.6895
                    rec_lon = 139.6917
                    st.warning("⚠️ 座標未設定です。デフォルト値を使用します。")

                new_quick_record = {
                    "日付": now_quick.date(), 
                    "時間": now_quick.time(), 
                    "lat": rec_lat,
                    "lon": rec_lon,
                    "種名": quick_species,
                    "方法": current_method,
                    "採集者": current_collector,
                    "備考": current_notes
                }
                
                append_data(DATA_FILE, new_quick_record)
                
                st.session_state.last_date = now_quick.date()
                st.session_state.last_time = now_quick.time()
                
                st.success(f"⚡️ {quick_species} を記録しました！")
                st.rerun()
            else:
                st.warning("種名を入力してください。")

    st.markdown("---")
    
    with st.form("common_settings_form"):
        st.subheader("⚙️ 共通設定 (採集者・方法)")
        st.caption("入力後、「設定を適用」を押してください。")
        
        c_collector = st.text_input("採集者", value=st.session_state.last_collector)
        c_method = st.selectbox("採集・確認方法", METHODS, index=st.session_state.last_method_index)
        c_notes = st.text_area("備考 (共通)", value=st.session_state.last_notes, placeholder="環境など")
        
        settings_submitted = st.form_submit_button("✅ 設定を適用 (Apply)")
        
        if settings_submitted:
            st.session_state.last_collector = c_collector
            try:
                st.session_state.last_method_index = METHODS.index(c_method)
            except:
                st.session_state.last_method_index = 0
            st.session_state.last_notes = c_notes
            st.success("設定を更新しました！")

    st.markdown("---")
    
    with st.expander("📝 日時などの手動調整 (詳細記録)"):
        with st.form("manual_record_form", clear_on_submit=True):
            input_date = st.date_input("日付", value=st.session_state.last_date)
            input_time = st.time_input("時間", value=st.session_state.last_time)
            
            species_name = st.text_input("種名 (標準和名)", placeholder="例: オオミズアオ")
            
            st.caption("※採集者・方法は上の設定が使われます。")
            submitted = st.form_submit_button("💾 詳細記録を保存")

            if submitted:
                if species_name:
                    current_collector = st.session_state.last_collector
                    try:
                        current_method = METHODS[st.session_state.last_method_index]
                    except:
                        current_method = METHODS[0]
                    current_notes = st.session_state.last_notes
                    
                    rec_lat = st.session_state.input_lat
                    rec_lon = st.session_state.input_lon
                    
                    new_record = {
                        "日付": input_date,
                        "時間": input_time,
                        "lat": rec_lat,
                        "lon": rec_lon,
                        "種名": species_name,
                        "方法": current_method,
                        "採集者": current_collector,
                        "備考": current_notes
                    }
                    append_data(DATA_FILE, new_record)
                    
                    st.session_state.last_date = input_date
                    st.session_state.last_time = input_time
                    
                    st.success(f"保存完了: {species_name}")
                else:
                    st.error("種名を入力してください。")

    st.markdown("---")
    with st.expander("🛠️ データの編集・削除"):
        st.info("編集後は「変更を適用して保存」を押してください。")
        current_df = load_data(DATA_FILE)
        edited_df = st.data_editor(
            current_df,
            num_rows="dynamic",
            use_container_width=True,
            key="data_editor"
        )
        if st.button("⚠️ 変更を適用して保存"):
            save_dataframe(DATA_FILE, edited_df)
            st.success("データを更新しました！")
            st.rerun()

        csv_data = current_df.to_csv(index=False).encode('utf-8_sig')
        st.download_button("CSVコピーを作成 (Download)", csv_data, f"{st.session_state.current_project}_export.csv", "text/csv")
