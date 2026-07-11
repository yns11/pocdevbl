import io
import os
import uuid
import datetime
from contextlib import contextmanager
from typing import Optional

import streamlit as st
import pandas as pd
from databricks import sql
from databricks.sdk.core import Config
from databricks.sdk import WorkspaceClient

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dématérialisation BL", layout="wide", page_icon="📋")

st.title("📋 Dématérialisation BL — Connexion Databricks SQL")
st.write("Version de production optimisée pour Databricks Apps (sans dépendance Java).")

# --- CONFIGURATION DES CHEMINS (Unity Catalog) ---
CATALOG_SCHEMA = "poc_bl.projet_livraison"
TABLE_SUIVI = "suivi_bl"
TABLE_PIECES = "pieces_jointes_bl"
PATH_VOLUME = "/Volumes/poc_bl/projet_livraison/images_bl"


# --- RESSOURCES DATABRICKS (créées une seule fois par instance de l'app) ---
@st.cache_resource
def get_databricks_config() -> Config:
    # Récupère automatiquement le contexte et le token de l'utilisateur connecté sur Databricks Apps
    return Config()


@st.cache_resource
def get_workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


try:
    cfg = get_databricks_config()
    server_hostname = cfg.host.replace("https://", "").rstrip("/")
except Exception as e:
    st.error(f"Erreur d'initialisation du contexte Databricks : {e}")
    cfg = None
    server_hostname = None


# --- CONNEXION SQL ---
@contextmanager
def get_connection():
    """Ouvre une connexion Databricks SQL, à réutiliser pour toutes les requêtes d'une même action utilisateur."""
    if not server_hostname:
        raise RuntimeError("Hôte Databricks introuvable. Vérifiez que l'application s'exécute dans Databricks Apps.")

    http_path = os.environ.get("DATABRICKS_HTTP_PATH")
    if not http_path:
        raise RuntimeError("Variable d'environnement DATABRICKS_HTTP_PATH manquante : impossible de joindre le SQL Warehouse.")

    connection = sql.connect(
        server_hostname=server_hostname,
        http_path=http_path,
        credentials_provider=lambda: cfg.credentials_provider,
    )
    try:
        yield connection
    finally:
        connection.close()


def run_query(connection, query: str, params: Optional[dict] = None, fetch: bool = False) -> Optional[pd.DataFrame]:
    """Exécute une requête sur une connexion déjà ouverte. Ne gère pas l'affichage : laisse l'appelant décider."""
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        if fetch:
            colnames = [desc[0] for desc in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=colnames)
    return None


# --- MESSAGES "FLASH" (persistent à travers un st.rerun) ---
def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def afficher_photo(chemin: str) -> None:
    if os.path.exists(chemin):
        st.image(chemin, use_container_width=True)
    else:
        st.caption("Fichier introuvable sur le volume.")


# --- ÉTAT DE SESSION ---
st.session_state.setdefault("photos_temporaires", [])
st.session_state.setdefault("camera_key", 0)

show_flash()

# --- SYSTEME D'ONGLETS ---
tab_ajout, tab_recherche = st.tabs(["➕ Ajouter un BL", "🔍 Rechercher & Consulter"])

# =====================================================================
# ONGLET 1 : AJOUT ET ÉCRITURE DANS LE LAKEHOUSE
# =====================================================================
with tab_ajout:
    st.header("Saisie d'un nouveau Bordereau")

    with st.form("form_nouveau_bl", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            num_bl = st.text_input("Numéro du BL *")
            nom_fournisseur = st.text_input("Nom du Fournisseur *")
        with col2:
            date_reception = st.date_input("Date de réception", datetime.date.today())
        submitted = st.form_submit_button(
            "💾 Enregistrer définitivement sur Databricks", type="primary", use_container_width=True
        )

    st.markdown("---")
    st.subheader("📸 Pièces jointes (Photos)")

    # La clé change à chaque photo ajoutée pour réinitialiser le widget et éviter un double ajout accidentel
    photo_capturee = st.camera_input("Prendre une page en photo", key=f"camera_{st.session_state.camera_key}")

    if photo_capturee:
        if st.button("➕ Ajouter cette photo au BL", use_container_width=True):
            st.session_state.photos_temporaires.append(photo_capturee.getvalue())
            st.session_state.camera_key += 1
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

    if submitted:
        num_bl = num_bl.strip()
        nom_fournisseur = nom_fournisseur.strip()

        if not num_bl or not nom_fournisseur:
            st.error("Veuillez remplir le numéro de BL et le nom du fournisseur.")
        elif not st.session_state.photos_temporaires:
            st.error("Veuillez prendre au moins une photo.")
        else:
            with st.spinner("Écriture dans le Data Lakehouse en cours..."):
                id_bl_unique = str(uuid.uuid4())
                bl_cree = False
                try:
                    with get_connection() as conn:
                        # Le BL "parent" est inséré en premier : si un transfert de photo échoue ensuite,
                        # on évite ainsi des lignes de pièces jointes orphelines sans BL associé.
                        run_query(
                            conn,
                            f"""
                                INSERT INTO {CATALOG_SCHEMA}.{TABLE_SUIVI}
                                    (id_bl, numero_bl, nom_fournisseur, date_reception, date_saisie)
                                VALUES (%(id_b)s, %(num)s, %(fourn)s, %(date_r)s, CURRENT_TIMESTAMP())
                            """,
                            params={
                                "id_b": id_bl_unique,
                                "num": num_bl,
                                "fourn": nom_fournisseur,
                                "date_r": date_reception,
                            },
                        )
                        bl_cree = True

                        w = get_workspace_client()
                        for idx, img_bytes in enumerate(st.session_state.photos_temporaires):
                            id_photo_unique = str(uuid.uuid4())
                            nom_fichier = f"{id_bl_unique}_{idx}_{id_photo_unique}.jpg"
                            chemin_unity_catalog = f"{PATH_VOLUME}/{nom_fichier}"

                            w.files.upload(chemin_unity_catalog, io.BytesIO(img_bytes), overwrite=True)

                            run_query(
                                conn,
                                f"""
                                    INSERT INTO {CATALOG_SCHEMA}.{TABLE_PIECES} (id_photo, id_bl, chemin_stockage)
                                    VALUES (%(id_p)s, %(id_b)s, %(path)s)
                                """,
                                params={"id_p": id_photo_unique, "id_b": id_bl_unique, "path": chemin_unity_catalog},
                            )

                    st.session_state.photos_temporaires = []
                    st.session_state.camera_key += 1
                    set_flash("success", f"BL n° {num_bl} sauvegardé avec succès dans Delta Lake !")
                    st.rerun()

                except Exception as e:
                    if bl_cree:
                        st.error(f"Le BL {num_bl} a été créé mais une erreur est survenue pendant le transfert des photos : {e}")
                    else:
                        st.error(f"Erreur lors de l'enregistrement du BL : {e}")

# =====================================================================
# ONGLET 2 : RECHERCHE ET LECTURE DEPUIS DELTA LAKE
# =====================================================================
with tab_recherche:
    st.header("Historique et Recherche")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        f_fournisseur = st.text_input("Filtrer par fournisseur").strip()
    with col_f2:
        f_numero = st.text_input("Filtrer par numéro de BL").strip()

    # Construction de la clause WHERE sécurisée (paramétrée) pour éviter les injections SQL
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
        FROM {CATALOG_SCHEMA}.{TABLE_SUIVI}
        WHERE {where_clause}
        ORDER BY date_saisie DESC
        LIMIT 50
    """

    df_bl = pd.DataFrame()
    photos_par_bl: dict = {}

    try:
        with get_connection() as conn:
            df_bl = run_query(conn, query_select_bl, params=params_filtre, fetch=True)

            # Une seule requête pour toutes les photos de tous les BL affichés (au lieu d'une requête par BL)
            if df_bl is not None and not df_bl.empty:
                id_params = {f"id_{i}": v for i, v in enumerate(df_bl["id_bl"].tolist())}
                placeholders = ", ".join(f"%({k})s" for k in id_params)
                query_photos = f"""
                    SELECT id_bl, chemin_stockage
                    FROM {CATALOG_SCHEMA}.{TABLE_PIECES}
                    WHERE id_bl IN ({placeholders})
                """
                df_photos_all = run_query(conn, query_photos, params=id_params, fetch=True)
                if df_photos_all is not None and not df_photos_all.empty:
                    photos_par_bl = df_photos_all.groupby("id_bl")["chemin_stockage"].apply(list).to_dict()
    except Exception as e:
        st.error(f"Erreur lors de la recherche : {e}")

    if df_bl is None or df_bl.empty:
        st.info("Aucun BL trouvé ou en attente de connexion Databricks.")
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

                    nouveau_nom = st.text_input(
                        f"Modifier le fournisseur pour le BL {row['numero_bl']}",
                        value=row["nom_fournisseur"],
                        key=f"edit_{id_bl}",
                    )
                    # Mise à jour uniquement sur clic explicite : évite une requête UPDATE à chaque caractère tapé
                    if st.button("💾 Renommer", key=f"save_{id_bl}"):
                        nouveau_nom = nouveau_nom.strip()
                        if nouveau_nom and nouveau_nom != row["nom_fournisseur"]:
                            try:
                                with get_connection() as conn:
                                    run_query(
                                        conn,
                                        f"""
                                            UPDATE {CATALOG_SCHEMA}.{TABLE_SUIVI}
                                            SET nom_fournisseur = %(new_name)s
                                            WHERE id_bl = %(id_b)s
                                        """,
                                        params={"new_name": nouveau_nom, "id_b": id_bl},
                                    )
                                set_flash("success", "Fournisseur mis à jour.")
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
