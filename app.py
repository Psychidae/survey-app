import streamlit as st
import pandas as pd
from datetime import datetime
import os
import folium
from streamlit_folium import st_folium
from folium.plugins import LocateControl

# --- 設定 ---
DATA_FILE = 'moth_data.csv'

# --- ページ設定 ---
st.set_page_config(page_title="学内蛾類調査マップ Offline", page_icon="🦋", layout="wide")

# --- 関数: データの読み込みと保存 ---
def load_data():
    # ファイルが存在するか確認
    if os.path.exists(DATA_FILE):
        try:
            # ファイルを読み込む
            return pd.read_csv(DATA_FILE)
        except pd.errors.EmptyDataError:
            # ファイルはあるが中身が空（0バイト）の場合のエラーをキャッチ
            # ヘッダー情報を持つ空のデータフレームを返す
            return pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])
    else:
        # ファイル自体がない場合
        return pd.DataFrame(columns=["日付", "時間", "lat", "lon", "種名", "方法", "採集者", "備考"])

def save_data(new_record):
    df = load_data()
    new_df = pd.DataFrame([new_record])
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)
    return df

# --- タイトル ---
st.title("🦋 学内蛾類調査フィールドノート (Offline Mode)")

# --- ローカル保存場所の表示 ---
current_dir = os.getcwd()
file_path = os.path.join(current_dir, DATA_FILE)
# クラウド環境ではパスが見えてもあまり意味がないため、ローカル実行時のみ役立ちます
st.caption(f"📂 Data Path: `{file_path}`")

# --- セッション状態の初期化 ---
if 'selected_lat' not in st.session_state:
    df_init = load_data()
    if not df_init.empty:
        last_rec = df_init.iloc[-1]
        st.session_state.selected_lat = last_rec['lat']
        st.session_state.selected_lon = last_rec['lon']
    else:
        # 初期値（前回値がない場合）
        st.session_state.selected_lat = 35.6895
        st.session_state.selected_lon = 139.6917

# --- 緯度経度フォームのコールバック関数 ---
def update_map_from_input():
    st.session_state.selected_lat = st.session_state.input_lat
    st.session_state.selected_lon = st.session_state.input_lon

# --- レイアウト ---
col1, col2 = st.columns([1, 2])

# --- 右カラム：地図 ---
with col2:
    st.subheader("🗺️ 位置決め")
    
    # オフライン用設定: 地図タイルを選べるようにする
    tile_option = st.radio(
        "地図モード", 
        ["OpenStreetMap (オンライン用)", "None (完全オフライン用・白地図)"], 
        index=0, 
        horizontal=True
    )
    
    # 地図の作成
    if tile_option == "None (完全オフライン用・白地図)":
        # タイルなし（グレー背景または白背景）
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=18,
            tiles=None
        )
        # グリッド線を追加して距離感をつかめるようにする
        folium.LatLngPopup().add_to(m)
    else:
        # 通常のOSM
        m = folium.Map(
            location=[st.session_state.selected_lat, st.session_state.selected_lon], 
            zoom_start=18
        )

    # 現在地ボタン
    LocateControl(auto_start=False).add_to(m)

    # 過去の記録をプロット
    # ※FontAwesome等の外部アイコンを使わず、CircleMarker（円）を使うことでオフラインでも描画を保証
    df = load_data()
    for index, row in df.iterrows():
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=6,
            color="green",
            fill=True,
            fill_color="green",
            fill_opacity=0.7,
            popup=f"{row['種名']} ({row['日付']})",
            tooltip=row['種名']
        ).add_to(m)

    # 現在の記録地点（赤いピン）
    folium.Marker(
        [st.session_state.selected_lat, st.session_state.selected_lon],
        popup="ここを記録します",
        icon=folium.Icon(color='red') # デフォルトアイコン
    ).add_to(m)

    # 地図を表示
    map_data = st_folium(m, height=500, width="100%", returned_objects=["last_clicked"])

    # クリック時の処理
    if map_data and map_data.get("last_clicked"):
        clicked_lat = map_data["last_clicked"]["lat"]
        clicked_lon = map_data["last_clicked"]["lng"]
        
        if (clicked_lat != st.session_state.selected_lat or 
            clicked_lon != st.session_state.selected_lon):
            st.session_state.selected_lat = clicked_lat
            st.session_state.selected_lon = clicked_lon
            st.rerun()

# --- 左カラム：入力フォーム ---
with col1:
    st.subheader("📝 記録データ")
    
    # --- 位置情報入力 ---
    st.markdown("**📍 位置情報**")
    st.info("ネットがない環境では、地図がグレーになる場合があります。その場合は「白地図」モードを選び、相対位置やグリッドを参考にしてください。")
    
    lat = st.number_input(
        "緯度", 
        value=st.session_state.selected_lat, 
        format="%.6f", 
        key="input_lat",
        on_change=update_map_from_input
    )
    lon = st.number_input(
        "経度", 
        value=st.session_state.selected_lon, 
        format="%.6f", 
        key="input_lon",
        on_change=update_map_from_input
    )
    
    st.markdown("---")
    
    # --- 入力フォーム ---
    with st.form("survey_form", clear_on_submit=True):
        now = datetime.now()
        input_date = st.date_input("日付", now)
        input_time = st.time_input("時間", now)
        
        species_name = st.text_input("種名 (標準和名)", placeholder="例: オオミズアオ")
        
        collection_method = st.selectbox(
            "採集・確認方法",
            ["Light trap (灯火採集)", "Net sweeping (ネット)", "Finding (見取り)", "Bait trap (ベイト)"]
        )
        
        collector = st.text_input("採集者", value="M. Yamaguchi")
        notes = st.text_area("備考", placeholder="環境など")
        
        submitted = st.form_submit_button("💾 記録を保存する")

        if submitted:
            if species_name:
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
                save_data(new_record)
                st.success(f"保存完了: {species_name}")
            else:
                st.error("種名を入力してください。")

    # データ管理
    with st.expander("保存データ管理"):
        st.dataframe(df)
        csv_data = df.to_csv(index=False).encode('utf-8_sig')
        st.download_button("CSVコピーを作成 (Download)", csv_data, "moth_data_export.csv", "text/csv")
