import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import pystac_client
import planetary_computer
import odc.stac
import numpy as np
import json
import plotly.express as px

st.set_page_config(layout="wide", page_title="Разметка дубрав")
st.title("🌳 Система разметки дубрав 🦫 🦆")

# Инициализация хранилищ
if "labeled_data" not in st.session_state:
    st.session_state.labeled_data = []
if "context_figs" not in st.session_state:
    st.session_state.context_figs = None

st.info("""
**Как работать:** 1. Нарисуйте большой прямоугольник, охватывающий нужный участок.
2. Выберите год и нажмите «Загрузить 3 снимка» для контекста.
3. Удалите старый прямоугольник.
4. Нарисуйте точные контуры поверх деревьев на карте и сохраните их кнопками на верхней панели.
""")

col1, col2 = st.columns([2, 1])

with col1:
    m = folium.Map(location=[48.70, 44.75], zoom_start=12, max_zoom=22)
    
    # Прячем флаг и копирайты
    hide_attribution = "<style>.leaflet-control-attribution {display: none !important;}</style>"
    m.get_root().html.add_child(folium.Element(hide_attribution))
    
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Esri Satellite (Высокое качество)', max_zoom=22, overlay=False, control=True
    ).add_to(m)
    
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google', name='Google Satellite', max_zoom=22, overlay=False, control=True
    ).add_to(m)
    
    folium.LayerControl().add_to(m)

    draw = Draw(
        draw_options={'polyline': False, 'rectangle': True, 'polygon': True, 'circle': False, 'marker': False, 'circlemarker': False},
        edit_options={'edit': True, 'remove': True}
    )
    m.add_child(draw)

    st_map = st_folium(m, width="100%", height=700)

with col2:
    if st_map["last_active_drawing"]:
        geom = st_map["last_active_drawing"]["geometry"]
        
        # --- БЛОК 1: КНОПКИ РАЗМЕТКИ  ---
        st.subheader("🎯 Панель разметки")
        st.write("Нарисуйте точный контур на карте и нажмите:")
        
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("🌳 Это ДУБ", use_container_width=True):
                st.session_state.labeled_data.append({
                    "type": "Feature", "properties": {"label": "Oak"}, "geometry": geom
                })
                st.success("Сохранено!")
        with btn_col2:
            if st.button("❌ Это НЕ дуб", use_container_width=True):
                st.session_state.labeled_data.append({
                    "type": "Feature", "properties": {"label": "Not_Oak"}, "geometry": geom
                })
                st.success("Сохранено!")
                
        st.markdown("---")
        
        # --- БЛОК 2: ЗАГРУЗКА И ОТОБРАЖЕНИЕ СНИМКОВ (ВНИЗУ) ---
        st.subheader("🗺️ Вспомогательные снимки")
        
        # По умолчанию индекс 2 (это 2025 год). 2026 год пока рано искать для июля.
        selected_year = st.selectbox("📅 Выберите год:", [2023, 2024, 2025, 2026], index=2)
        
        if st.button("Загрузить 3 снимка для этой зоны", use_container_width=True):
            coords = geom["coordinates"][0]
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            bounds = (min(lons), min(lats), max(lons), max(lats))
            
            try:
                with st.spinner('Ищем лучшие снимки в архиве (10-15 сек)...'):
                    catalog = pystac_client.Client.open(
                        "https://planetarycomputer.microsoft.com/api/stac/v1",
                        modifier=planetary_computer.sign_inplace,
                    )
                    
                    months_search = [
                        ("Апрель", f"{selected_year}-04-01/{selected_year}-04-30"),
                        ("Май", f"{selected_year}-05-01/{selected_year}-05-31"),
                        ("Июль", f"{selected_year}-07-01/{selected_year}-07-31")
                    ]
                    
                    selected_items = []
                    plot_titles = []
                    
                    for name, d_range in months_search:
                        search = catalog.search(
                            collections=["sentinel-2-l2a"], bbox=bounds, datetime=d_range,
                            query={"eo:cloud_cover": {"lt": 30}}
                        )
                        items = list(search.items())
                        if items:
                            items.sort(key=lambda x: x.properties["eo:cloud_cover"])
                            selected_items.append(items[0])
                            plot_titles.append(f"{name}: {items[0].datetime.strftime('%Y-%m-%d')}")
                    
                    if not selected_items:
                        st.error(f"Я не знаю как такое может быть, но безоблачных снимков за {selected_year} год не найдено!!!")
                    else:
                        dataset = odc.stac.load(
                            selected_items, bands=["B04", "B03", "B02"],
                            bbox=bounds, crs="EPSG:32638", resolution=10
                        )
                        
                        data_np = dataset.to_array(dim="band").to_numpy()
                        data_np = np.transpose(data_np, (1, 0, 2, 3))
                        data_tensor = np.clip((data_np.astype(np.float32) / 10000.0) * 2.5, 0, 1)

                        figs = []
                        for i in range(len(selected_items)):
                            rgb_img = np.transpose(data_tensor[i], (1, 2, 0))
                            rgb_img_uint8 = (rgb_img * 255).astype(np.uint8)
                            fig = px.imshow(rgb_img_uint8, title=plot_titles[i])
                            fig.update_xaxes(visible=False)
                            fig.update_yaxes(visible=False)
                            fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), hovermode=False)
                            figs.append(fig)
                        
                        st.session_state.context_figs = figs

            except Exception as e:
                st.error(f"Ошибка загрузки (возможно, слишком большая область). Детали: {e}")

        # Отрисовка картинок под кнопкой загрузки
        if st.session_state.context_figs is not None:
            for fig in st.session_state.context_figs:
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

    else:
        st.write("Начните с выделения области на карте слева.")

st.markdown("---")
st.subheader(f"Размечено точных участков: {len(st.session_state.labeled_data)}")

# Панель управления сохраненными данными (В самом низу экрана)
if len(st.session_state.labeled_data) > 0:
    ctrl_col1, ctrl_col2 = st.columns([1, 3])
    
    with ctrl_col1:
        if st.button("⏪ Отменить последнее", help="Удалить последний добавленный полигон"):
            st.session_state.labeled_data.pop()
            st.rerun()
            
    with ctrl_col2:
        geojson_dict = {"type": "FeatureCollection", "features": st.session_state.labeled_data}
        geojson_str = json.dumps(geojson_dict, ensure_ascii=False)
        st.download_button(
            label="📥 Скачать результаты (GeoJSON)",
            data=geojson_str, file_name="oak_labels.geojson", mime="application/geo+json"
        )
