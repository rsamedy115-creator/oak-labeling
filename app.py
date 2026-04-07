import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import pystac_client
import planetary_computer
import odc.stac
import matplotlib.pyplot as plt
import numpy as np
import geopandas as gpd
from shapely.geometry import shape
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
    # Базовая карта с гугл-спутником
    m = folium.Map(location=[48.70, 44.75], zoom_start=11)
    
    # Добавляем слой Google Satellite
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google',
        name='Google Satellite',
        overlay=False,
        control=True
    ).add_to(m)

    # Добавляем инструмент рисования (только полигоны)
    draw = Draw(
        draw_options={
            'polyline': False,
            'rectangle': True,
            'polygon': True,
            'circle': False,
            'marker': False,
            'circlemarker': False
        },
        edit_options={'edit': False}
    )
    m.add_child(draw)

    # Рендерим карту и ловим то, что нарисовал пользователь
    st_map = st_folium(m, width="100%", height=600)

with col2:
    st.subheader("2. Анализ и разметка")
    
    # Если пользователь что-то нарисовал
    if st_map["last_active_drawing"]:
        geom = st_map["last_active_drawing"]["geometry"]
        poly = shape(geom)
        bounds = poly.bounds # (minx, miny, maxx, maxy)
        
        st.info("Полигон получен! Загружаем исторические снимки...")
        
        # Блок загрузки данных со STAC
        try:
            with st.spinner('Связь со спутниковым архивом... (около 5-10 сек)'):
                catalog = pystac_client.Client.open(
                    "https://planetarycomputer.microsoft.com/api/stac/v1",
                    modifier=planetary_computer.sign_inplace,
                )
                
                # Ищем данные
                search = catalog.search(
                    collections=["sentinel-2-l2a"],
                    bbox=bounds,
                    datetime="2023-04-01/2023-08-31",
                    query={"eo:cloud_cover": {"lt": 10}}
                )
                items = list(search.items())
                
                # Фильтруем наши 3 ключевые даты
                target_dates = ['2023-04-09', '2023-05-19', '2023-07-06']
                selected = []
                seen = set()
                for item in items:
                    dt = item.datetime.strftime("%Y-%m-%d")
                    if dt in target_dates and dt not in seen:
                        selected.append(item)
                        seen.add(dt)
                
                selected = sorted(selected, key=lambda x: x.datetime)
                
                # Скачиваем пиксели
                dataset = odc.stac.load(
                    selected,
                    bands=["B04", "B03", "B02"], # Только RGB для визуализации экспертам
                    bbox=bounds,
                    crs="EPSG:32638",
                    resolution=10
                )
                
                data_np = dataset.to_array(dim="band").to_numpy()
                data_np = np.transpose(data_np, (1, 0, 2, 3)) # (Time, Channels, H, W)
                data_tensor = np.clip((data_np.astype(np.float32) / 10000.0) * 2.5, 0, 1)

            # Отрисовка снимков
            fig, axes = plt.subplots(1, 3, figsize=(12, 4))
            for i, date in enumerate(target_dates):
                if i < data_tensor.shape[0]:
                    rgb_img = np.transpose(data_tensor[i], (1, 2, 0))
                    axes[i].imshow(rgb_img)
                    axes[i].set_title(date)
                axes[i].axis('off')
            
            st.pyplot(fig)

            # Кнопки разметки
            st.write("Что находится в выделенной зоне?")
            btn_col1, btn_col2 = st.columns(2)
            
            with btn_col1:
                if st.button("🌳 Точно ДУБ", use_container_width=True):
                    st.session_state.labeled_data.append({"geometry": poly, "label": "Oak"})
                    st.success("Сохранено как Дуб!")
            
            with btn_col2:
                if st.button("❌ Точно НЕ дуб", use_container_width=True):
                    st.session_state.labeled_data.append({"geometry": poly, "label": "Not_Oak"})
                    st.success("Сохранено как НЕ дуб!")

        except Exception as e:
            st.error(f"Ошибка загрузки данных. Возможно, слишком большой полигон. Попробуйте нарисовать меньше. Детали: {e}")
    else:
        st.write("Нарисуйте прямоугольник или полигон на карте слева, чтобы увидеть снимки.")

# Нижний блок: Экспорт результатов
st.markdown("---")
st.subheader(f"Размечено участков: {len(st.session_state.labeled_data)}")

if len(st.session_state.labeled_data) > 0:
    # Конвертируем в GeoDataFrame
    gdf = gpd.GeoDataFrame(st.session_state.labeled_data, crs="EPSG:4326")
    geojson_str = gdf.to_json()
    
    st.download_button(
        label="📥 Скачать результаты (GeoJSON)",
        data=geojson_str,
        file_name="oak_labels.geojson",
        mime="application/geo+json",
    )
