import streamlit as st
import datetime
import uuid
import os
from PIL import Image


from databricks.connect import DatabricksSession

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dématérialisation BL", layout="wide", page_icon="📋")

st.title("📋 Dématérialisation BL — Connexion Databricks Delta")

# --- INITIALISATION DE LA SESSION DATABRICKS ---
@st.cache_resource
def get_spark_session():
    # Récupère automatiquement le contexte sécurisé de l'utilisateur connecté sur Databricks
    return DatabricksSession.builder.getOrCreate()

spark = get_spark_session()

# --- CONFIGURATION DES CHEMINS (Unity Catalog) ---
CATALOG_SCHEMA = "poc_bl.projet_livraison"
# Chemin d'accès au volume sous l'architecture POSIX de Databricks
PATH_VOLUME = "/Volumes/poc_bl/projet_livraison/images_bl/"

# On garde le session_state UNIQUEMENT pour stocker les photos temporairement 
# le temps que l'utilisateur clique sur "Ajouter" avant la sauvegarde finale.
if "photos_temporaires" not in st.session_state:
    st.session_state.photos_temporaires = []

# --- SYSTEME D'ONGLETS ---
tab_ajout, tab_recherche = st.tabs(["➕ Ajouter un BL", "🔍 Rechercher & Consulter"])

# =====================================================================
# ONGLET 1 : AJOUT ET ÉCRITURE DANS LES TABLES DELTA
# =====================================================================
with tab_ajout:
    st.header("Saisie d'un nouveau Bordereau")
    
    col1, col2 = st.columns(2)
    with col1:
        num_bl = st.text_input("Numéro du BL *")
        nom_fournisseur = st.text_input("Nom du Fournisseur *")
    with col2:
        date_reception = st.date_input("Date de réception", datetime.date.today())
    
    st.markdown("---")
    st.subheader("📸 Pièces jointes (Photos)")
    
    photo_capturee = st.camera_input("Prendre une page en photo")
    
    if photo_capturee:
        if st.button("➕ Ajouter cette photo au BL", use_container_width=True):
            # On conserve le fichier brut (octets) en mémoire temporaire Streamlit
            st.session_state.photos_temporaires.append(photo_capturee.getvalue())
            st.toast("Photo ajoutée temporairement !", icon="✅")
            st.rerun()

    if st.session_state.photos_temporaires:
        st.write(f"📂 **Photos prêtes à être sauvegardées sur Databricks ({len(st.session_state.photos_temporaires)}) :**")
        cols_miniatures = st.columns(len(st.session_state.photos_temporaires))
        for idx, img_bytes in enumerate(st.session_state.photos_temporaires):
            with cols_miniatures[idx]:
                st.image(img_bytes, caption=f"Page {idx + 1}", width=120)
        
        if st.button("🗑️ Effacer les photos en cours", type="secondary"):
            st.session_state.photos_temporaires = []
            st.rerun()

    st.markdown("---")
    
    if st.button("💾 Enregistrer définitivement sur Databricks", type="primary", use_container_width=True):
        if not num_bl or not nom_fournisseur:
            st.error("Veuillez remplir le numéro de BL et le nom du fournisseur.")
        elif not st.session_state.photos_temporaires:
            st.error("Veuillez prendre au moins une photo.")
        else:
            with st.spinner("Écriture dans le Data Lakehouse en cours..."):
                try:
                    # 1. Générer un ID unique pour ce BL (Clé primaire)
                    id_bl_unique = str(uuid.uuid4())
                    
                    # 2. Sauvegarder les fichiers physiques dans le Volume Unity Catalog
                    for idx, img_bytes in enumerate(st.session_state.photos_temporaires):
                        id_photo_unique = str(uuid.uuid4())
                        nom_fichier = f"{id_bl_unique}_{idx}_{id_photo_unique}.jpg"
                        chemin_complet_volume = os.path.join(PATH_VOLUME, nom_fichier)
                        
                        # Écriture physique sur le Volume cloud
                        with open(chemin_complet_volume, "wb") as f:
                            f.write(img_bytes)
                        
                        # Insertion du lien dans la table secondaire
                        query_photo = f"""
                            INSERT INTO {CATALOG_SCHEMA}.pieces_jointes_bl (id_photo, id_bl, chemin_stockage)
                            VALUES ('{id_photo_unique}', '{id_bl_unique}', '{chemin_complet_volume}')
                        """
                        spark.sql(query_photo)
                    
                    # 3. Insertion des métadonnées textuelles dans la table principale
                    query_bl = f"""
                        INSERT INTO {CATALOG_SCHEMA}.suivi_bl (id_bl, numero_bl, nom_fournisseur, date_reception, date_saisie)
                        VALUES ('{id_bl_unique}', '{num_bl}', '{nom_fournisseur}', '{date_reception}', current_timestamp())
                    """
                    spark.sql(query_bl)
                    
                    # Libération de la mémoire
                    st.session_state.photos_temporaires = []
                    st.success(f"BL n°{num_bl} sauvegardé de manière permanente dans Delta Lake !")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Erreur lors de la sauvegarde Databricks : {e}")

# =====================================================================
# ONGLET 2 : RECHERCHE ET LECTURE DEPUIS DELTA LAKE
# =====================================================================
with tab_recherche:
    st.header("Historique et Recherche")
    
    # 1. Zone des filtres
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        f_fournisseur = st.text_input("Filtrer par fournisseur")
    with col_f2:
        f_numero = st.text_input("Filtrer par numéro de BL")
        
    # 2. Construction de la requête SQL dynamique avec filtres
    conditions = ["1=1"] # Condition de base toujours vraie
    if f_fournisseur:
        conditions.append(f"lower(nom_fournisseur) LIKE '%{f_fournisseur.lower()}%'")
    if f_numero:
        conditions.append(f"lower(numero_bl) LIKE '%{f_numero.lower()}%'")
        
    where_clause = " AND ".join(conditions)
    
    # Requête pour récupérer les BL (limité aux 50 derniers pour la performance)
    query_select_bl = f"""
        SELECT id_bl, numero_bl, nom_fournisseur, date_reception 
        FROM {CATALOG_SCHEMA}.suivi_bl 
        WHERE {where_clause}
        ORDER BY date_saisie DESC LIMIT 50
    """
    
    try:
        # Récupération sous forme de DataFrame Pandas pour Streamlit
        df_bl = spark.sql(query_select_bl).toPandas()
        
        if df_bl.empty:
            st.info("Aucun BL ne correspond à votre recherche.")
        else:
            st.write(f"Résultat : {len(df_bl)} BL trouvé(s)")
            
            for index, row in df_bl.iterrows():
                id_bl = row['id_bl']
                
                # Récupérer les photos associées à CE BL spécifique
                query_photos = f"SELECT chemin_stockage FROM {CATALOG_SCHEMA}.pieces_jointes_bl WHERE id_bl = '{id_bl}'"
                df_photos = spark.sql(query_photos).toPandas()
                nb_photos = len(df_photos)
                
                with st.expander(f"📄 BL n° {row['numero_bl']} — {row['nom_fournisseur']} ({nb_photos} photo(s))"):
                    col_txt, col_imgs = st.columns([1, 1])
                    
                    with col_txt:
                        st.write(f"**Date de livraison :** {row['date_reception']}")
                        
                        # Modification directe dans la table Delta
                        nouveau_nom = st.text_input(
                            f"Modifier le fournisseur pour le BL {row['numero_bl']}", 
                            value=row['nom_fournisseur'], 
                            key=f"edit_{id_bl}"
                        )
                        if nouveau_nom != row['nom_fournisseur']:
                            query_update = f"""
                                UPDATE {CATALOG_SCHEMA}.suivi_bl 
                                SET nom_fournisseur = '{nouveau_nom}' 
                                WHERE id_bl = '{id_bl}'
                            """
                            spark.sql(query_update)
                            st.success("Mis à jour dans Delta Lake !")
                            st.rerun()
                            
                    with col_imgs:
                        if nb_photos > 0:
                            # Affichage des photos lues depuis le Volume
                            if nb_photos > 1:
                                sub_tabs = st.tabs([f"Page {i+1}" for i in range(nb_photos)])
                                for idx, path in enumerate(df_photos['chemin_stockage']):
                                    with sub_tabs[idx]:
                                        # Le volume est accessible directement en lecture Python
                                        if os.path.exists(path):
                                            st.image(path, use_container_width=True)
                            else:
                                single_path = df_photos['chemin_stockage'].iloc[0]
                                if os.path.exists(single_path):
                                    st.image(single_path, use_container_width=True)
                        else:
                            st.warning("Aucune photo rattachée.")
    except Exception as e:
        st.error(f"Erreur de lecture de la base Databricks : {e}")
