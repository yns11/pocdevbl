import streamlit as st
import datetime
from PIL import Image

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dématérialisation BL", layout="wide", page_icon="📋")

st.title("📋 Gestionnaire de Bons de Livraison (BL) - Version Multi-Photos")
st.write("Environnement de test local.")

# --- INITIALISATION DE LA MÉMOIRE LOCALE ---
if "base_bl" not in st.session_state:
    st.session_state.base_bl = []

# NOUVEAU : Mémoire temporaire pour accumuler les photos d'un BL avant l'enregistrement final
if "photos_temporaires" not in st.session_state:
    st.session_state.photos_temporaires = []

# --- SYSTÈME D'ONGLETS ---
tab_ajout, tab_recherche = st.tabs(["➕ Ajouter un BL", "🔍 Rechercher & Consulter"])

# =====================================================================
# ONGLET 1 : AJOUT D'UN NOUVEAU BL (AVEC PHOTOS MULTIPLES)
# =====================================================================
with tab_ajout:
    st.header("Saisie d'un nouveau Bordereau")
    
    # 1. Champs d'informations généraux (Hors formulaire pour gérer dynamiquement l'état des photos)
    col1, col2 = st.columns(2)
    with col1:
        num_bl = st.text_input("Numéro du BL *")
        nom_fournisseur = st.text_input("Nom du Fournisseur *")
    with col2:
        date_reception = st.date_input("Date de réception", datetime.date.today())
    
    st.markdown("---")
    st.subheader("📸 Pièces jointes (Photos)")
    
    # 2. Zone de capture de photo
    photo_capturee = st.camera_input("Prendre une page ou une pièce jointe en photo")
    
    # Bouton pour ajouter la photo capturée à la liste temporaire
    if photo_capturee:
        if st.button("➕ Ajouter cette photo au BL", use_container_width=True):
            image_pil = Image.open(photo_capturee)
            st.session_state.photos_temporaires.append(image_pil)
            st.toast("Photo ajoutée à la liste temporaire !", icon="✅")
            # Forcer un rechargement pour réinitialiser la caméra pour la photo suivante
            st.rerun()

    # 3. Affichage des miniatures des photos déjà capturées pour ce BL
    if st.session_state.photos_temporaires:
        st.write(f"📂 **Photos prêtes à être enregistrées ({len(st.session_state.photos_temporaires)}) :**")
        # Affichage en ligne (colonnes) des miniatures
        cols_miniatures = st.columns(max(len(st.session_state.photos_temporaires), 1))
        for idx, img in enumerate(st.session_state.photos_temporaires):
            with cols_miniatures[idx]:
                st.image(img, caption=f"Page {idx + 1}", width=120)
        
        # Bouton pour vider les photos en cas d'erreur
        if st.button("🗑️ Effacer toutes les photos en cours", type="secondary"):
            st.session_state.photos_temporaires = []
            st.rerun()

    st.markdown("---")
    
    # 4. Bouton final d'enregistrement du BL complet
    if st.button("💾 Enregistrer définitivement le BL", type="primary", use_container_width=True):
        if not num_bl or not nom_fournisseur:
            st.error("Veuillez remplir le numéro de BL et le nom du fournisseur.")
        elif not st.session_state.photos_temporaires:
            st.error("Veuillez prendre et ajouter au moins une photo avant d'enregistrer.")
        else:
            # Créer le BL avec sa LISTE de photos
            nouveau_bl = {
                "numero": num_bl,
                "fournisseur": nom_fournisseur,
                "date": date_reception,
                "photos": list(st.session_state.photos_temporaires) # Copie de la liste
            }
            
            # Sauvegarde dans notre fausse base de données
            st.session_state.base_bl.append(nouveau_bl)
            
            # Réinitialisation de la mémoire temporaire pour le prochain BL
            st.session_state.photos_temporaires = []
            
            st.success(f"Le BL n°{num_bl} a été créé avec succès avec {len(nouveau_bl['photos'])} photo(s) !")
            # Petit délai pour que l'utilisateur voie le succès puis reset des champs textuels
            st.rerun()

# =====================================================================
# ONGLET 2 : RECHERCHE ET CONSULTATION (AVEC CAROUSEL / DIAPORAMA)
# =====================================================================
with tab_recherche:
    st.header("Historique et Recherche")
    
    if len(st.session_state.base_bl) == 0:
        st.info("Aucun BL enregistré pour le moment. Allez dans l'onglet 'Ajouter un BL' pour commencer.")
    else:
        # 1. Barres de filtres
        st.subheader("Filtres")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtre_fournisseur = st.text_input("Filtrer par nom de fournisseur")
        with col_f2:
            filtre_numero = st.text_input("Filtrer par numéro de BL")
            
        # 2. Logique de filtrage
        bl_filtres = []
        for bl in st.session_state.base_bl:
            match_fournisseur = filtre_fournisseur.lower() in bl["fournisseur"].lower()
            match_numero = filtre_numero.lower() in bl["numero"].lower()
            if match_fournisseur and match_numero:
                bl_filtres.append(bl)
                
        st.write(f"Résultat : {len(bl_filtres)} BL trouvé(s)")
        
        # 3. Affichage des BL
        for bl in bl_filtres:
            cle_unique = f"edit_{bl['numero']}"
            nb_photos = len(bl["photos"])
            
            with st.expander(f"📄 BL n° {bl['numero']} — Fournisseur : {bl['fournisseur']} ({nb_photos} photo(s))"):
                col_texte, col_images = st.columns([1, 1])
                
                with col_texte:
                    st.write(f"**Numéro de BL :** {bl['numero']}")
                    st.write(f"**Date d'enregistrement :** {bl['date']}")
                    
                    nouveau_nom = st.text_input(
                        f"Modifier le nom du fournisseur pour le BL {bl['numero']}", 
                        value=bl['fournisseur'], 
                        key=cle_unique
                    )
                    if nouveau_nom != bl['fournisseur']:
                        bl['fournisseur'] = nouveau_nom
                        st.success("Nom mis à jour !")
                        st.rerun()
                        
                with col_images:
                    st.write(f"**Pièces jointes ({nb_photos}) :**")
                    
                    # S'il y a plusieurs photos, on propose un système de navigation par onglets internes
                    if nb_photos > 1:
                        # Crée un sous-onglet par photo
                        onglets_photos = st.tabs([f"Page {i+1}" for i in range(nb_photos)])
                        for idx, onglet in enumerate(onglets_photos):
                            with onglet:
                                st.image(bl['photos'][idx], use_container_width=True)
                    else:
                        # S'il n'y a qu'une photo, affichage direct
                        st.image(bl['photos'][0], use_container_width=True)