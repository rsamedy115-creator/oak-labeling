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

# Инициализация хранилищ в сессии
if "labeled_data" not in st.session_state:
    st.session_state.labeled_data = []
# Хранилище для картинок контекста
if "context_fig" not in st.session_state:
    st.session_state.context_fig = None

# Инструкция для преподавателей
st.info("""
**Как работать:** 1. Нарисуйте большой прямоугольник, охватывающий весь лес.
2. Нажмите «Загрузить исторические снимки» (справа), чтобы получить контекст.
3. Нарисуйте маленькие точные полигоны поверх конкретных деревьев.
4. Сохраняйте их кнопками «Это ДУБ» или «Это НЕ дуб».
""")

col1, col2 = st.columns([2, 1])

with col1:
    # max_zoom=22 позволяет приближать карту до каждого листика (если есть качество)
    m = folium.Map(location=[48.70, 44.75], zoom_start=12, max_zoom=22)
    
    # Решение проблемы с флагом: жестко скрываем блок атрибуции через CSS
    hide_attribution = """
    <style>
    .leaflet-control-attribution {display: none !important;}
    </style>
    """
    m.get_root().html.add_child(folium.Element(hide_attribution))
    
    # Слой Esri (очень часто в России качество у него сильно выше, чем у гугла)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satellite (Высокое качество)',
        max_zoom=22,
        overlay=False,
        control=True
    ).add_to(m)

    # Слой Google как запасной
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google',
        name='Google Satellite',
        max_zoom=22,
        overlay=False,
        control=True
    ).add_to(m)
    
    # Добавляем переключатель слоев (справа сверху на карте)
    folium.LayerControl().add_to(m)

    # Инструменты рисования (добавлено удаление - remove: True)
    draw = Draw(
        draw_options={'polyline': False, 'rectangle': True, 'polygon': True, 'circle': False, 'marker': False, 'circlemarker': False},
        edit_options={'edit': True, 'remove': True}
    )
    m.add_child(draw)

    # Увеличил высоту карты до 700 для удобства
    st_map = st_folium(m, width="100%", height=700)

with col2:
    if st_map["last_active_drawing"]:
        # Текущий нарисованный полигон
        geom = st_map["last_active_drawing"]["geometry"]
        
        st.subheader("Шаг 1: Контекст")
        # Кнопка теперь не загружает данные автоматически, а ждет клика
        if st.button("🗺️ Загрузить 3 снимка для этой зоны", use_container_width=True):
            coords = geom["coordinates"][0]
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            bounds = (min(lons), min(lats), max(lons), max(lats))
            
            try:
                with st.spinner('Скачиваем снимки из архива (5-10 сек)...'):
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
                
                # Записываем картинку в кэш сессии, чтобы она не пропадала!
                st.session_state.context_fig = fig

            except Exception as e:
                st.error(f"Ошибка загрузки (возможно, слишком большая область). Детали: {e}")

        # Если картинка есть в кэше — показываем её
        if st.session_state.context_fig is not None:
            st.pyplot(st.session_state.context_fig)
            
            st.markdown("---")
            st.subheader("Шаг 2: Разметка")
            st.write("Нарисуйте точный контур на карте и нажмите нужную кнопку:")
            
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("🌳 Это ДУБ", use_container_width=True):
                    # Сохраняем ТОЛЬКО последнюю активную фигуру
                    st.session_state.labeled_data.append({
                        "type": "Feature",
                        "properties": {"label": "Oak"},
                        "geometry": geom
                    })
                    st.success("Сохранено!")
            with btn_col2:
                if st.button("❌ Это НЕ дуб", use_container_width=True):
                    st.session_state.labeled_data.append({
                        "type": "Feature",
                        "properties": {"label": "Not_Oak"},
                        "geometry": geom
                    })
                    st.success("Сохранено!")
    else:
        st.write("Начните с выделения области на карте слева.")

st.markdown("---")
st.subheader(f"Размечено точных участков: {len(st.session_state.labeled_data)}")

if len(st.session_state.labeled_data) > 0:
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
