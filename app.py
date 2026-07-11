import streamlit as st
import datetime
import uuid
import os
import pandas as pd
from PIL import Image
from databricks import sql
from databricks.sdk.core import Config
from databricks.sdk import WorkspaceClient

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dématérialisation BL", layout="wide", page_icon="📋")

st.title("📋 Dématérialisation BL — Connexion Databricks SQL")
st.write("Version de production optimisée pour Databricks Apps (sans dépendance Java).")

# --- INITIALISATION DE LA CONFIGURATION DATABRICKS ---
@st.cache_resource
def get_databricks_config():
    # Récupère automatiquement le contexte et le token de l'utilisateur connecté sur Databricks Apps
    return Config()

try:
    cfg = get_databricks_config()
    server_hostname = cfg.host.replace("https://", "")
except Exception as e:
    st.error(f"Erreur d'initialisation du contexte Databricks : {e}")
    server_hostname = None

# --- CONFIGURATION DES CHEMINS (Unity Catalog) ---
CATALOG_SCHEMA = "poc_bl.projet_livraison"
PATH_VOLUME = "/Volumes/poc_bl/projet_livraison/images_bl/"

# --- FONCTION UTILITAIRE EXÉCUTION SQL ---
def execute_sql_query(query, params=None):
    """Exécute une requête SQL de manière sécurisée via le Databricks SQL Connector"""
    if not server_hostname:
        st.error("Hôte Databricks introuvable. Vérifiez que l'application s'exécute dans Databricks Apps.")
        return pd.DataFrame()
        
    # Databricks Apps injecte automatiquement le chemin HTTP du Warehouse par défaut dans l'environnement,
    # sinon vous pouvez spécifier l'ID de votre SQL Warehouse manuellement.
    http_path = os.environ.get("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/votre_id_warehouse")

    try:
        with sql.connect(
            server_hostname=server_hostname,
            http_path=http_path,
            credentials_provider=lambda: cfg.credentials_provider
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                if cursor.description:  # Si la requête retourne des lignes (SELECT)
                    colnames = [desc[0] for desc in cursor.description]
                    return pd.DataFrame(cursor.fetchall(), columns=colnames)
                connection.commit()
                return None
    except Exception as error:
        st.error(f"Erreur SQL : {error}")
        return pd.DataFrame() if "SELECT" in query.upper() else None

# --- MÉMOIRE TEMPORAIRE STREAMLIT ---
if "photos_temporaires" not in st.session_state:
    st.session_state.photos_temporaires = []

# --- SYSTEME D'ONGLETS ---
tab_ajout, tab_recherche = st.tabs(["➕ Ajouter un BL", "🔍 Rechercher & Consulter"])

# =====================================================================
# ONGLET 1 : AJOUT ET ÉCRITURE DANS LE LAKEHOUSE
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
            st.session_state.photos_temporaires.append(photo_capturee.getvalue())
            st.toast("Photo ajoutée temporairement !", icon="✅")
            st.rerun()

    if st.session_state.photos_temporaires:
        st.write(f"📂 **Photos prêtes à être sauvegardées ({len(st.session_state.photos_temporaires)}) :**")
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
                id_bl_unique = str(uuid.uuid4())
                sauvegarde_reussie = True
                
                # 1. Sauvegarde des fichiers physiques dans le Volume Unity Catalog
                for idx, img_bytes in enumerate(st.session_state.photos_temporaires):
                    id_photo_unique = str(uuid.uuid4())
                    nom_fichier = f"{id_bl_unique}_{idx}_{id_photo_unique}.jpg"
                    chemin_complet_volume = os.path.join(PATH_VOLUME, nom_fichier)
                    
                    try:
                        # Initialisation du client Workspace (utilise le token de l'App automatiquement)
                        w = WorkspaceClient()
                        
                        # Définition du chemin d'accès cloud pour Unity Catalog
                        id_photo_unique = str(uuid.uuid4())
                        nom_fichier = f"{id_bl_unique}_{idx}_{id_photo_unique}.jpg"
                        
                        # Le chemin UC officiel n'utilise pas le dossier racine local /Volumes
                        chemin_unity_catalog = f"/Volumes/poc_bl/projet_livraison/images_bl/{nom_fichier}"
                        
                        # Téléversement direct et sécurisé via l'API de Databricks (plus de conflit de droits Linux !)
                        with w.files.upload(chemin_unity_catalog, img_bytes) as response:
                            pass
                            
                        # Insertion du lien dans la table secondaire
                        query_photo = f"""
                            INSERT INTO {CATALOG_SCHEMA}.pieces_jointes_bl (id_photo, id_bl, chemin_stockage)
                            VALUES (%(id_p)s, %(id_b)s, %(path)s)
                        """
                        execute_sql_query(query_photo, params={
                            "id_p": id_photo_unique, 
                            "id_b": id_bl_unique, 
                            "path": chemin_unity_catalog
                        })
                        
                    except Exception as e:
                        st.error(f"Erreur de transfert de la photo {idx+1} vers le Volume UC : {e}")
                        sauvegarde_reussie = False
                
                # 2. Insertion des métadonnées textuelles dans la table principale
                if sauvegarde_reussie:
                    query_bl = f"""
                        INSERT INTO {CATALOG_SCHEMA}.suivi_bl (id_bl, numero_bl, nom_fournisseur, date_reception, date_saisie)
                        VALUES (%(id_b)s, %(num)s, %(fourn)s, %(date_r)s, CURRENT_TIMESTAMP())
                    """
                    execute_sql_query(query_bl, params={
                        "id_b": id_bl_unique,
                        "num": num_bl,
                        "fourn": nom_fournisseur,
                        "date_r": date_reception
                    })
                    
                    # Libération de la mémoire
                    st.session_state.photos_temporaires = []
                    st.success(f"BL n° {num_bl} sauvegardé avec succès dans Delta Lake !")
                    st.rerun()

# =====================================================================
# ONGLET 2 : RECHERCHE ET LECTURE DEPUIS DELTA LAKE
# =====================================================================
with tab_recherche:
    st.header("Historique et Recherche")
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        f_fournisseur = st.text_input("Filtrer par fournisseur")
    with col_f2:
        f_numero = st.text_input("Filtrer par numéro de BL")
        
    # Construction de la clause WHERE sécurisée pour éviter les injections SQL
    conditions = ["1=1"]
    params_filtre = {}
    
    if f_fournisseur:
        conditions.append("LOWER(nom_fournisseur) LIKE %(f_fourn)s")
        params_filtre["f_fourn"] = f"%{f_fournisseur.lower()}%"
    if f_numero:
        conditions.append("LOWER(numero_bl) LIKE %(f_num)s")
        params_filtre["f_num"] = f"%{f_numero.lower()}%"
        
    where_clause = " AND ".join(conditions)
    
    query_select_bl = f"""
        SELECT id_bl, numero_bl, nom_fournisseur, date_reception 
        FROM {CATALOG_SCHEMA}.suivi_bl 
        WHERE {where_clause}
        ORDER BY date_saisie DESC LIMIT 50
    """
    
    df_bl = execute_sql_query(query_select_bl, params=params_filtre)
    
    if df_bl is None or df_bl.empty:
        st.info("Aucun BL trouvé ou en attente de connexion Databricks.")
    else:
        st.write(f"Résultat : {len(df_bl)} BL trouvé(s)")
        
        for index, row in df_bl.iterrows():
            id_bl = row['id_bl']
            
            # Récupérer les photos rattachées
            query_photos = f"SELECT chemin_stockage FROM {CATALOG_SCHEMA}.pieces_jointes_bl WHERE id_bl = %(id_b)s"
            df_photos = execute_sql_query(query_photos, params={"id_b": id_bl})
            nb_photos = len(df_photos) if df_photos is not None else 0
            
            with st.expander(f"📄 BL n° {row['numero_bl']} — {row['nom_fournisseur']} ({nb_photos} photo(s))"):
                col_txt, col_imgs = st.columns([1, 1])
                
                with col_txt:
                    st.write(f"**Date de livraison :** {row['date_reception']}")
                    
                    nouveau_nom = st.text_input(
                        f"Modifier le fournisseur pour le BL {row['numero_bl']}", 
                        value=row['nom_fournisseur'], 
                        key=f"edit_{id_bl}"
                    )
                    if nouveau_nom != row['nom_fournisseur']:
                        query_update = f"""
                            UPDATE {CATALOG_SCHEMA}.suivi_bl 
                            SET nom_fournisseur = %(new_name)s 
                            WHERE id_bl = %(id_b)s
                        """
                        execute_sql_query(query_update, params={"new_name": nouveau_nom, "id_b": id_bl})
                        st.success("Base mise à jour !")
                        st.rerun()
                        
                with col_imgs:
                    if nb_photos > 0:
                        if nb_photos > 1:
                            sub_tabs = st.tabs([f"Page {i+1}" for i in range(nb_photos)])
                            for idx, path in enumerate(df_photos['chemin_stockage']):
                                with sub_tabs[idx]:
                                    if os.path.exists(path):
                                        st.image(path, use_container_width=True)
                                    else:
                                        st.caption("Fichier introuvable sur le volume.")
                        else:
                            single_path = df_photos['chemin_stockage'].iloc[0]
                            if os.path.exists(single_path):
                                st.image(single_path, use_container_width=True)
                            else:
                                st.caption("Fichier introuvable sur le volume.")
                    else:
                        st.warning("Aucune photo rattachée.")
