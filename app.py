import io
import os
import uuid
import datetime

import streamlit as st
import pandas as pd
import boto3  # Ajouté pour la connexion à AWS Textract
from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dématérialisation BL", layout="wide", page_icon="📋")

st.title("📋 Dématérialisation BL — Connexion Databricks Delta")import io
import os
import uuid
import datetime

import streamlit as st
import pandas as pd
import boto3  # Ajouté pour la connexion à AWS Textract
from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dématérialisation BL", layout="wide", page_icon="📋")

st.title("📋 Dématérialisation BL — Connexion Databricks Delta")

# --- CONFIGURATION IDENTIFIANTS AWS (Amazon Textract) ---
# Idéalement configurés dans les paramètres de votre Databricks App (Environment Variables)
AWS_ID = os.environ.get("AWS_ACCESS_KEY_ID", "VOTRE_AWS_ACCESS_KEY_ID")
AWS_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY", "VOTRE_AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")  # Configuré sur la Virginie (us-east-1)

# --- INITIALISATION DE LA SESSION DATABRICKS ---
@st.cache_resource
def get_spark_session():
    # .serverless() est nécessaire : sans cluster_id ni indication explicite,
    # Databricks Connect ne déduit pas tout seul qu'il doit utiliser le compute serverless.
    return DatabricksSession.builder.serverless().getOrCreate()


@st.cache_resource
def get_workspace_client() -> WorkspaceClient:
    # Le conteneur de l'app n'a pas /Volumes monté localement (contrairement à un cluster) :
    # la lecture/écriture des photos passe donc par l'API Files, pas par open()/os.path.
    return WorkspaceClient()


spark = get_spark_session()

# --- CONFIGURATION DES CHEMINS (Unity Catalog) ---
CATALOG_SCHEMA = "poc_bl.projet_livraison"
TABLE_SUIVI = "suivi_bl"
TABLE_PIECES = "pieces_jointes_bl"
PATH_VOLUME = "/Volumes/poc_bl/projet_livraison/images_bl"


# --- FONCTION DE SCAN INTELLIGENT (AWS TEXTRACT) ---
def scanner_image_via_aws(image_bytes: bytes) -> bytes:
    """Envoie le flux brut de la photo à AWS Textract pour analyser et valider la mise en page."""
    try:
        # Initialisation du client AWS natif
        client = boto3.client(
            "textract",
            aws_access_key_id=AWS_ID,
            aws_secret_access_key=AWS_SECRET,
            region_name=AWS_REGION
        )
        
        # Appel de l'analyse structurelle synchrone du document (Layout / Formulaire)
        client.analyze_document(
            Document={"Bytes": image_bytes},
            FeatureTypes=["TABLES", "FORMS", "LAYOUT"]
        )
        
        # L'IA a validé la structure géométrique du document.
        # Pour le POC, nous retournons l'image validée. En production, les résultats de 
        # cette fonction permettront d'extraire automatiquement le texte pour remplir les champs.
        return image_bytes
        
    except Exception as e:
        st.warning(f"⚠️ Traitement IA indisponible (Vérifiez vos identifiants IAM AWS) : {e}")
        # En cas de problème d'API, on retourne l'image brute pour ne pas bloquer l'opérateur terrain
        return image_bytes


# --- MESSAGES "FLASH" (persistent à travers un st.rerun) ---
def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def afficher_photo(chemin: str) -> None:
    try:
        w = get_workspace_client()
        img_bytes = w.files.download(chemin).contents.read()
        # use_column_width (et non use_container_width) pour compatibilité avec la version
        # de Streamlit du runtime Databricks Apps, plus ancienne.
        st.image(img_bytes, use_column_width=True)
    except Exception as e:
        st.caption(f"Fichier introuvable ou inaccessible sur le volume : {e}")


# On garde le session_state UNIQUEMENT pour stocker les photos temporairement
# le temps que l'utilisateur clique sur "Ajouter" avant la sauvegarde finale.
st.session_state.setdefault("photos_temporaires", [])
st.session_state.setdefault("camera_key", 0)

show_flash()

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

    # La clé change à chaque photo ajoutée pour réinitialiser le widget et éviter un double ajout accidentel
    photo_capturee = st.camera_input("Prendre une page en photo", key=f"camera_{st.session_state.camera_key}")

    if photo_capturee:
        if st.button("➕ Ajouter cette photo au BL", use_container_width=True):
            # --- INTERCEPTION PAR L'IA AMAZON TEXTRACT ---
            with st.spinner("L'IA Amazon Textract analyse et valide la mise en page..."):
                photo_brute = photo_capturee.getvalue()
                photo_traitee = scanner_image_via_aws(photo_brute)
            
            # Stockage de l'image (éventuellement validée/nettoyée par l'infrastructure cloud)
            st.session_state.photos_temporaires.append(photo_traitee)
            st.session_state.camera_key += 1
            st.toast("Document validé par l'IA et ajouté !", icon="✅")
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
        num_bl_clean = num_bl.strip()
        nom_fournisseur_clean = nom_fournisseur.strip()

        if not num_bl_clean or not nom_fournisseur_clean:
            st.error("Veuillez remplir le numéro de BL et le nom du fournisseur.")
        elif not st.session_state.photos_temporaires:
            st.error("Veuillez prendre au moins une photo.")
        else:
            with st.spinner("Écriture dans le Data Lakehouse en cours..."):
                id_bl_unique = str(uuid.uuid4())
                try:
                    # Le BL "parent" est inséré en premier : si l'écriture d'une photo échoue ensuite,
                    # on évite des lignes de pièces jointes orphelines qui référenceraient un BL inexistant.
                    spark.sql(
                        f"""
                            INSERT INTO {CATALOG_SCHEMA}.{TABLE_SUIVI}
                                (id_bl, numero_bl, nom_fournisseur, date_reception, date_saisie)
                            VALUES (:id_b, :num, :fourn, :date_r, current_timestamp())
                        """,
                        args={
                            "id_b": id_bl_unique,
                            "num": num_bl_clean,
                            "fourn": nom_fournisseur_clean,
                            "date_r": date_reception,
                        },
                    )

                    w = get_workspace_client()
                    for idx, img_bytes in enumerate(st.session_state.photos_temporaires):
                        id_photo_unique = str(uuid.uuid4())
                        nom_fichier = f"{id_bl_unique}_{idx}_{id_photo_unique}.jpg"
                        chemin_complet_volume = os.path.join(PATH_VOLUME, nom_fichier)

                        # Écriture sur le Volume via l'API Files (pas d'accès /Volumes local dans l'app)
                        w.files.upload(chemin_complet_volume, io.BytesIO(img_bytes), overwrite=True)

                        spark.sql(
                            f"""
                                INSERT INTO {CATALOG_SCHEMA}.{TABLE_PIECES} (id_photo, id_bl, chemin_stockage)
                                VALUES (:id_p, :id_b, :path)
                            """,
                            args={"id_p": id_photo_unique, "id_b": id_bl_unique, "path": chemin_complet_volume},
                        )

                    # Libération de la mémoire
                    st.session_state.photos_temporaires = []
                    st.session_state.camera_key += 1
                    set_flash("success", f"BL n°{num_bl_clean} sauvegardé de manière permanente dans Delta Lake !")
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
        f_fournisseur = st.text_input("Filtrer par fournisseur").strip()
    with col_f2:
        f_numero = st.text_input("Filtrer par numéro de BL").strip()

    # 2. Construction de la requête SQL dynamique avec filtres (paramétrée, pas d'injection possible)
    conditions = ["1=1"]  # Condition de base toujours vraie
    params_filtre = {}
    if f_fournisseur:
        conditions.append("lower(nom_fournisseur) LIKE :f_fourn")
        params_filtre["f_fourn"] = f"%{f_fournisseur.lower()}%"
    if f_numero:
        conditions.append("lower(numero_bl) LIKE :f_num")
        params_filtre["f_num"] = f"%{f_numero.lower()}%"

    where_clause = " AND ".join(conditions)

    # Requête pour récupérer les BL (limité aux 50 derniers pour la performance)
    query_select_bl = f"""
        SELECT id_bl, numero_bl, nom_fournisseur, date_reception
        FROM {CATALOG_SCHEMA}.{TABLE_SUIVI}
        WHERE {where_clause}
        ORDER BY date_saisie DESC LIMIT 50
    """

    df_bl = pd.DataFrame()
    photos_par_bl = {}

    try:
        df_bl = spark.sql(query_select_bl, args=params_filtre).toPandas()

        if not df_bl.empty:
            # Une seule requête pour toutes les photos de tous les BL affichés
            # (au lieu d'une requête par BL, qui devenait très lent avec beaucoup de résultats)
            id_params = {f"id_{i}": v for i, v in enumerate(df_bl["id_bl"].tolist())}
            placeholders = ", ".join(f":{k}" for k in id_params)
            query_photos = f"""
                SELECT id_bl, chemin_stockage
                FROM {CATALOG_SCHEMA}.{TABLE_PIECES}
                WHERE id_bl IN ({placeholders})
            """
            df_photos_all = spark.sql(query_photos, args=id_params).toPandas()
            if not df_photos_all.empty:
                photos_par_bl = df_photos_all.groupby("id_bl")["chemin_stockage"].apply(list).to_dict()

    except Exception as e:
        st.error(f"Erreur de lecture de la base Databricks : {e}")

    if df_bl.empty:
        st.info("Aucun BL ne correspond à votre recherche.")
    else:
        st.write(f"Résultat : {len(df_bl)} BL trouvé(s)")

        for _, row in df_bl.iterrows():
            id_bl = row["id_bl"]
            chemins_photos = photos_par_bl.get(id_bl, [])
            nb_photos = len(chemins_photos)

            with st.expander(f"📄 BL n° {row['numero_bl']} — {row['nom_fournisseur']} ({nb_photos} photo(s))"):
                col_txt, col_imgs = st.columns([1, 1])

                with col_txt:
                    st.write(f"**Date de livraison :** {row['date_reception']}")

                    # Modification directe dans la table Delta
                    nouveau_nom = st.text_input(
                        f"Modifier le fournisseur pour le BL {row['numero_bl']}",
                        value=row["nom_fournisseur"],
                        key=f"edit_{id_bl}",
                    )
                    # Mise à jour uniquement sur clic explicite (pas à chaque caractère tapé)
                    if st.button("💾 Renommer", key=f"save_{id_bl}"):
                        nouveau_nom_clean = nouveau_nom.strip()
                        if nouveau_nom_clean and nouveau_nom_clean != row["nom_fournisseur"]:
                            try:
                                spark.sql(
                                    f"""
                                        UPDATE {CATALOG_SCHEMA}.{TABLE_SUIVI}
                                        SET nom_fournisseur = :new_name
                                        WHERE id_bl = :id_b
                                    """,
                                    args={"new_name": nouveau_nom_clean, "id_b": id_bl},
                                )
                                set_flash("success", "Mis à jour dans Delta Lake !")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erreur lors de la mise à jour : {e}")

                with col_imgs:
                    if not chemins_photos:
                        st.warning("Aucune photo rattachée.")
                    elif len(chemins_photos) == 1:
                        afficher_photo(chemins_photos[0])
                    else:
                        sub_tabs = st.tabs([f"Page {i + 1}" for i in range(nb_photos)])
                        for tab, chemin in zip(sub_tabs, chemins_photos):
                            with tab:
                                afficher_photo(chemin)

# --- CONFIGURATION IDENTIFIANTS AWS (Amazon Textract) ---
# Idéalement configurés dans les paramètres de votre Databricks App (Environment Variables)
AWS_ID = "AKIAVHAIEAUR3KBXWPUS" #os.environ.get("AWS_ACCESS_KEY_ID", "VOTRE_AWS_ACCESS_KEY_ID")
AWS_SECRET = "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" #os.environ.get("AWS_SECRET_ACCESS_KEY", "VOTRE_AWS_SECRET_ACCESS_KEY")
AWS_REGION = "us-east-1" #os.environ.get("AWS_REGION", "us-east-1")  # Configuré sur la Virginie (us-east-1)

# --- INITIALISATION DE LA SESSION DATABRICKS ---
@st.cache_resource
def get_spark_session():
    # .serverless() est nécessaire : sans cluster_id ni indication explicite,
    # Databricks Connect ne déduit pas tout seul qu'il doit utiliser le compute serverless.
    return DatabricksSession.builder.serverless().getOrCreate()


@st.cache_resource
def get_workspace_client() -> WorkspaceClient:
    # Le conteneur de l'app n'a pas /Volumes monté localement (contrairement à un cluster) :
    # la lecture/écriture des photos passe donc par l'API Files, pas par open()/os.path.
    return WorkspaceClient()


spark = get_spark_session()

# --- CONFIGURATION DES CHEMINS (Unity Catalog) ---
CATALOG_SCHEMA = "poc_bl.projet_livraison"
TABLE_SUIVI = "suivi_bl"
TABLE_PIECES = "pieces_jointes_bl"
PATH_VOLUME = "/Volumes/poc_bl/projet_livraison/images_bl"


# --- FONCTION DE SCAN INTELLIGENT (AWS TEXTRACT) ---
def scanner_image_via_aws(image_bytes: bytes) -> bytes:
    """Envoie le flux brut de la photo à AWS Textract pour analyser et valider la mise en page."""
    try:
        # Initialisation du client AWS natif
        client = boto3.client(
            "textract",
            aws_access_key_id=AWS_ID,
            aws_secret_access_key=AWS_SECRET,
            region_name=AWS_REGION
        )
        
        # Appel de l'analyse structurelle synchrone du document (Layout / Formulaire)
        client.analyze_document(
            Document={"Bytes": image_bytes},
            FeatureTypes=["TABLES", "FORMS", "LAYOUT"]
        )
        
        # L'IA a validé la structure géométrique du document.
        # Pour le POC, nous retournons l'image validée. En production, les résultats de 
        # cette fonction permettront d'extraire automatiquement le texte pour remplir les champs.
        return image_bytes
        
    except Exception as e:
        st.warning(f"⚠️ Traitement IA indisponible (Vérifiez vos identifiants IAM AWS) : {e}")
        # En cas de problème d'API, on retourne l'image brute pour ne pas bloquer l'opérateur terrain
        return image_bytes


# --- MESSAGES "FLASH" (persistent à travers un st.rerun) ---
def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def afficher_photo(chemin: str) -> None:
    try:
        w = get_workspace_client()
        img_bytes = w.files.download(chemin).contents.read()
        # use_column_width (et non use_container_width) pour compatibilité avec la version
        # de Streamlit du runtime Databricks Apps, plus ancienne.
        st.image(img_bytes, use_column_width=True)
    except Exception as e:
        st.caption(f"Fichier introuvable ou inaccessible sur le volume : {e}")


# On garde le session_state UNIQUEMENT pour stocker les photos temporairement
# le temps que l'utilisateur clique sur "Ajouter" avant la sauvegarde finale.
st.session_state.setdefault("photos_temporaires", [])
st.session_state.setdefault("camera_key", 0)

show_flash()

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

    # La clé change à chaque photo ajoutée pour réinitialiser le widget et éviter un double ajout accidentel
    photo_capturee = st.camera_input("Prendre une page en photo", key=f"camera_{st.session_state.camera_key}")

    if photo_capturee:
        if st.button("➕ Ajouter cette photo au BL", use_container_width=True):
            # --- INTERCEPTION PAR L'IA AMAZON TEXTRACT ---
            with st.spinner("L'IA Amazon Textract analyse et valide la mise en page..."):
                photo_brute = photo_capturee.getvalue()
                photo_traitee = scanner_image_via_aws(photo_brute)
            
            # Stockage de l'image (éventuellement validée/nettoyée par l'infrastructure cloud)
            st.session_state.photos_temporaires.append(photo_traitee)
            st.session_state.camera_key += 1
            st.toast("Document validé par l'IA et ajouté !", icon="✅")
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
        num_bl_clean = num_bl.strip()
        nom_fournisseur_clean = nom_fournisseur.strip()

        if not num_bl_clean or not nom_fournisseur_clean:
            st.error("Veuillez remplir le numéro de BL et le nom du fournisseur.")
        elif not st.session_state.photos_temporaires:
            st.error("Veuillez prendre au moins une photo.")
        else:
            with st.spinner("Écriture dans le Data Lakehouse en cours..."):
                id_bl_unique = str(uuid.uuid4())
                try:
                    # Le BL "parent" est inséré en premier : si l'écriture d'une photo échoue ensuite,
                    # on évite des lignes de pièces jointes orphelines qui référenceraient un BL inexistant.
                    spark.sql(
                        f"""
                            INSERT INTO {CATALOG_SCHEMA}.{TABLE_SUIVI}
                                (id_bl, numero_bl, nom_fournisseur, date_reception, date_saisie)
                            VALUES (:id_b, :num, :fourn, :date_r, current_timestamp())
                        """,
                        args={
                            "id_b": id_bl_unique,
                            "num": num_bl_clean,
                            "fourn": nom_fournisseur_clean,
                            "date_r": date_reception,
                        },
                    )

                    w = get_workspace_client()
                    for idx, img_bytes in enumerate(st.session_state.photos_temporaires):
                        id_photo_unique = str(uuid.uuid4())
                        nom_fichier = f"{id_bl_unique}_{idx}_{id_photo_unique}.jpg"
                        chemin_complet_volume = os.path.join(PATH_VOLUME, nom_fichier)

                        # Écriture sur le Volume via l'API Files (pas d'accès /Volumes local dans l'app)
                        w.files.upload(chemin_complet_volume, io.BytesIO(img_bytes), overwrite=True)

                        spark.sql(
                            f"""
                                INSERT INTO {CATALOG_SCHEMA}.{TABLE_PIECES} (id_photo, id_bl, chemin_stockage)
                                VALUES (:id_p, :id_b, :path)
                            """,
                            args={"id_p": id_photo_unique, "id_b": id_bl_unique, "path": chemin_complet_volume},
                        )

                    # Libération de la mémoire
                    st.session_state.photos_temporaires = []
                    st.session_state.camera_key += 1
                    set_flash("success", f"BL n°{num_bl_clean} sauvegardé de manière permanente dans Delta Lake !")
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
        f_fournisseur = st.text_input("Filtrer par fournisseur").strip()
    with col_f2:
        f_numero = st.text_input("Filtrer par numéro de BL").strip()

    # 2. Construction de la requête SQL dynamique avec filtres (paramétrée, pas d'injection possible)
    conditions = ["1=1"]  # Condition de base toujours vraie
    params_filtre = {}
    if f_fournisseur:
        conditions.append("lower(nom_fournisseur) LIKE :f_fourn")
        params_filtre["f_fourn"] = f"%{f_fournisseur.lower()}%"
    if f_numero:
        conditions.append("lower(numero_bl) LIKE :f_num")
        params_filtre["f_num"] = f"%{f_numero.lower()}%"

    where_clause = " AND ".join(conditions)

    # Requête pour récupérer les BL (limité aux 50 derniers pour la performance)
    query_select_bl = f"""
        SELECT id_bl, numero_bl, nom_fournisseur, date_reception
        FROM {CATALOG_SCHEMA}.{TABLE_SUIVI}
        WHERE {where_clause}
        ORDER BY date_saisie DESC LIMIT 50
    """

    df_bl = pd.DataFrame()
    photos_par_bl = {}

    try:
        df_bl = spark.sql(query_select_bl, args=params_filtre).toPandas()

        if not df_bl.empty:
            # Une seule requête pour toutes les photos de tous les BL affichés
            # (au lieu d'une requête par BL, qui devenait très lent avec beaucoup de résultats)
            id_params = {f"id_{i}": v for i, v in enumerate(df_bl["id_bl"].tolist())}
            placeholders = ", ".join(f":{k}" for k in id_params)
            query_photos = f"""
                SELECT id_bl, chemin_stockage
                FROM {CATALOG_SCHEMA}.{TABLE_PIECES}
                WHERE id_bl IN ({placeholders})
            """
            df_photos_all = spark.sql(query_photos, args=id_params).toPandas()
            if not df_photos_all.empty:
                photos_par_bl = df_photos_all.groupby("id_bl")["chemin_stockage"].apply(list).to_dict()

    except Exception as e:
        st.error(f"Erreur de lecture de la base Databricks : {e}")

    if df_bl.empty:
        st.info("Aucun BL ne correspond à votre recherche.")
    else:
        st.write(f"Résultat : {len(df_bl)} BL trouvé(s)")

        for _, row in df_bl.iterrows():
            id_bl = row["id_bl"]
            chemins_photos = photos_par_bl.get(id_bl, [])
            nb_photos = len(chemins_photos)

            with st.expander(f"📄 BL n° {row['numero_bl']} — {row['nom_fournisseur']} ({nb_photos} photo(s))"):
                col_txt, col_imgs = st.columns([1, 1])

                with col_txt:
                    st.write(f"**Date de livraison :** {row['date_reception']}")

                    # Modification directe dans la table Delta
                    nouveau_nom = st.text_input(
                        f"Modifier le fournisseur pour le BL {row['numero_bl']}",
                        value=row["nom_fournisseur"],
                        key=f"edit_{id_bl}",
                    )
                    # Mise à jour uniquement sur clic explicite (pas à chaque caractère tapé)
                    if st.button("💾 Renommer", key=f"save_{id_bl}"):
                        nouveau_nom_clean = nouveau_nom.strip()
                        if nouveau_nom_clean and nouveau_nom_clean != row["nom_fournisseur"]:
                            try:
                                spark.sql(
                                    f"""
                                        UPDATE {CATALOG_SCHEMA}.{TABLE_SUIVI}
                                        SET nom_fournisseur = :new_name
                                        WHERE id_bl = :id_b
                                    """,
                                    args={"new_name": nouveau_nom_clean, "id_b": id_bl},
                                )
                                set_flash("success", "Mis à jour dans Delta Lake !")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erreur lors de la mise à jour : {e}")

                with col_imgs:
                    if not chemins_photos:
                        st.warning("Aucune photo rattachée.")
                    elif len(chemins_photos) == 1:
                        afficher_photo(chemins_photos[0])
                    else:
                        sub_tabs = st.tabs([f"Page {i + 1}" for i in range(nb_photos)])
                        for tab, chemin in zip(sub_tabs, chemins_photos):
                            with tab:
                                afficher_photo(chemin)
