import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import pystac_client
import planetary_computer
import odc.stac
import matplotlib.pyplot as plt
import numpy as np
import json

# Настройка страницы
st.set_page_config(layout="wide", page_title="Разметка дубрав")
st.title("🌳 Система разметки дубрав: Волго-Ахтубинская пойма")

# Инициализация хранилища данных в сессии
if "labeled_data" not in st.session_state:
    st.session_state.labeled_data = []

# Левая колонка - карта, Правая - снимки и кнопки
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("1. Нарисуйте полигон")
    m = folium.Map(location=[48.70, 44.75], zoom_start=11)
    
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google',
        name='Google Satellite',
        overlay=False,
        control=True
    ).add_to(m)

    draw = Draw(
        draw_options={'polyline': False, 'rectangle': True, 'polygon': True, 'circle': False, 'marker': False, 'circlemarker': False},
        edit_options={'edit': False}
    )
    m.add_child(draw)

    st_map = st_folium(m, width="100%", height=600)

with col2:
    st.subheader("2. Анализ и разметка")
    
    if st_map["last_active_drawing"]:
        geom = st_map["last_active_drawing"]["geometry"]
        
        # Вычисляем bounds без Shapely (на чистом Python)
        coords = geom["coordinates"][0]
        lons = [p[0] for p in coords]
        lats = [p[1] for p in coords]
        bounds = (min(lons), min(lats), max(lons), max(lats))
        
        st.info("Полигон получен! Загружаем исторические снимки...")
        
        try:
            with st.spinner('Связь со спутниковым архивом... (около 5-10 сек)'):
                catalog = pystac_client.Client.open(
                    "https://planetarycomputer.microsoft.com/api/stac/v1",
                    modifier=planetary_computer.sign_inplace,
                )
                
                search = catalog.search(
                    collections=["sentinel-2-l2a"],
                    bbox=bounds,
                    datetime="2023-04-01/2023-08-31",
                    query={"eo:cloud_cover": {"lt": 10}}
                )
                items = list(search.items())
                
                target_dates = ['2023-04-09', '2023-05-19', '2023-07-06']
                selected = []
                seen = set()
                for item in items:
                    dt = item.datetime.strftime("%Y-%m-%d")
                    if dt in target_dates and dt not in seen:
                        selected.append(item)
                        seen.add(dt)
                
                selected = sorted(selected, key=lambda x: x.datetime)
                
                dataset = odc.stac.load(
                    selected,
                    bands=["B04", "B03", "B02"],
                    bbox=bounds,
                    crs="EPSG:32638",
                    resolution=10
                )
                
                data_np = dataset.to_array(dim="band").to_numpy()
                data_np = np.transpose(data_np, (1, 0, 2, 3))
                data_tensor = np.clip((data_np.astype(np.float32) / 10000.0) * 2.5, 0, 1)

            fig, axes = plt.subplots(1, 3, figsize=(12, 4))
            for i, date in enumerate(target_dates):
                if i < data_tensor.shape[0]:
                    rgb_img = np.transpose(data_tensor[i], (1, 2, 0))
                    axes[i].imshow(rgb_img)
                    axes[i].set_title(date)
                axes[i].axis('off')
            
            st.pyplot(fig)

            st.write("Что находится в выделенной зоне?")
            btn_col1, btn_col2 = st.columns(2)
            
            with btn_col1:
                if st.button("🌳 Точно ДУБ", use_container_width=True):
                    # Сохраняем в сыром виде для GeoJSON
                    st.session_state.labeled_data.append({
                        "type": "Feature",
                        "properties": {"label": "Oak"},
                        "geometry": geom
                    })
                    st.success("Сохранено как Дуб!")
            
            with btn_col2:
                if st.button("❌ Точно НЕ дуб", use_container_width=True):
                    st.session_state.labeled_data.append({
                        "type": "Feature",
                        "properties": {"label": "Not_Oak"},
                        "geometry": geom
                    })
                    st.success("Сохранено как НЕ дуб!")

        except Exception as e:
            st.error(f"Ошибка загрузки данных. Детали: {e}")
    else:
        st.write("Нарисуйте прямоугольник или полигон на карте слева, чтобы увидеть снимки.")

st.markdown("---")
st.subheader(f"Размечено участков: {len(st.session_state.labeled_data)}")

if len(st.session_state.labeled_data) > 0:
    # Формируем итоговый GeoJSON на чистом Python
    geojson_dict = {
        "type": "FeatureCollection",
        "features": st.session_state.labeled_data
    }
    geojson_str = json.dumps(geojson_dict, ensure_ascii=False)
    
    st.download_button(
        label="📥 Скачать результаты (GeoJSON)",
        data=geojson_str,
        file_name="oak_labels.geojson",
        mime="application/geo+json",
    )
