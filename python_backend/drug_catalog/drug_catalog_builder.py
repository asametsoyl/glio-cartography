#!/usr/bin/env python3
"""
GBM Ligand-Receptor Drug Catalog Builder
Queries the ChEMBL REST API to refresh clinical drug metadata.
"""

import os
import sys
import json
import time
import tempfile
import logging
import urllib.request
import urllib.parse
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("drug_catalog_builder")

CHEMBL_BASE_URL = "https://www.ebi.ac.uk/chembl/api/data/molecule"


def translate_phase(max_phase):
    """Translate numerical ChEMBL max_phase to Roman numerals."""
    if max_phase is None:
        return "Preklinik"
    try:
        val = float(max_phase)
    except (ValueError, TypeError):
        return "Preklinik"

    if val >= 4.0:
        return "IV"
    elif val >= 3.0:
        return "III"
    elif val >= 2.0:
        return "II"
    elif val >= 1.0:
        return "I"
    else:
        return "Preklinik"


def fetch_from_chembl(chembl_id=None, drug_name=None):
    """
    Fetch molecule data from ChEMBL REST API by ID or name.
    Enforces a polite 1.0 second delay after requests.
    """
    url = None
    if chembl_id:
        url = f"{CHEMBL_BASE_URL}/{chembl_id}.json"
    elif drug_name:
        # Search by exact name
        query = urllib.parse.quote(drug_name)
        url = f"{CHEMBL_BASE_URL}.json?pref_name__iexact={query}"

    if not url:
        return None

    try:
        logger.debug(f"Querying URL: {url}")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Glio-Cartography/1.2 (Science Agent; EBI API Client)"
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            # Respect rate limit of ChEMBL REST API (1s delay)
            time.sleep(1.0)
            return res_data
    except Exception as e:
        logger.warning(f"ChEMBL API request failed for id={chembl_id}, name={drug_name}: {e}")
        time.sleep(1.0)
        return None


def parse_chembl_molecule(mol_data):
    """Extract relevant fields from the molecule response dict."""
    if not mol_data:
        return None

    # Handle search endpoint (wrapped in "molecules") vs single detail lookup
    if "molecules" in mol_data:
        mols = mol_data.get("molecules", [])
        if not mols:
            return None
        mol = mols[0]
    else:
        mol = mol_data

    # Map variables
    chembl_id = mol.get("molecule_chembl_id")
    max_phase = mol.get("max_phase")
    withdrawn = mol.get("withdrawn_flag", False)
    
    # Extract synonyms/aliases
    aliases = []
    syns = mol.get("molecule_synonyms", [])
    if isinstance(syns, list):
        for s in syns:
            syn_name = s.get("synonyms")
            if syn_name and syn_name not in aliases:
                aliases.append(syn_name)

    return {
        "chemblId": chembl_id,
        "max_phase": max_phase,
        "withdrawn": withdrawn,
        "aliases": aliases,
        "drugClass": mol.get("molecule_type")
    }


def refresh_catalog(catalog_path, progress_callback=None):
    """
    Reads the existing drug_catalog.json, refreshes all entries via ChEMBL API,
    and updates the JSON file atomically.
    """
    path = Path(catalog_path)
    if not path.exists():
        logger.error(f"Catalog file not found: {path}")
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read/parse drug catalog: {e}")
        return False

    catalog = data.get("catalog", {})
    total = len(catalog)
    logger.info(f"Starting refresh for {total} drug catalog entries...")

    success_count = 0
    for idx, (axis, entry) in enumerate(catalog.items(), 1):
        drug_name = entry.get("drug")
        chembl_id = entry.get("chemblId")

        if progress_callback:
            progress_callback(idx, total, f"Sorgulanıyor: {drug_name}")

        logger.info(f"[{idx}/{total}] Fetching details for '{drug_name}' (ChEMBL ID: {chembl_id})...")
        
        # Try fetching by ChEMBL ID first, then by name
        res_raw = None
        if chembl_id:
            res_raw = fetch_from_chembl(chembl_id=chembl_id)
        
        # If ID lookup failed or wasn't available, search by name
        if not res_raw and drug_name:
            res_raw = fetch_from_chembl(drug_name=drug_name)

        parsed = parse_chembl_molecule(res_raw)
        
        if parsed:
            # Update entry fields
            if parsed["chemblId"]:
                entry["chemblId"] = parsed["chemblId"]
            
            # Map phase
            entry["phase"] = translate_phase(parsed["max_phase"])
            
            # Map FDA status based on Phase IV and withdrawn flag
            if parsed["max_phase"] == 4 and not parsed["withdrawn"]:
                entry["fdaStatus"] = "Approved"
            elif entry.get("fdaStatus") == "Approved" and parsed["withdrawn"]:
                entry["fdaStatus"] = "Investigational"  # withdrawn or downgraded
            
            # Merge aliases
            curr_aliases = entry.get("aliases", [])
            for alias in parsed["aliases"]:
                if alias not in curr_aliases and alias.lower() != drug_name.lower():
                    curr_aliases.append(alias)
            entry["aliases"] = curr_aliases

            success_count += 1
            logger.info(f"   Success: {drug_name} -> Phase {entry['phase']}, FDA: {entry['fdaStatus']}")
        else:
            logger.warning(f"   Could not fetch/parse data for {drug_name}. Retaining original local values.")

    # Update metadata
    data["_meta"]["last_fetched"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["_meta"]["last_fetched_source"] = "ChEMBL REST API"
    data["_meta"]["notes"] = f"Refreshed {success_count}/{total} entries successfully."

    # Write atomically
    temp_fd, temp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as tmp_file:
            json.dump(data, tmp_file, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        logger.info("Drug catalog JSON updated atomically.")
    except Exception as e:
        logger.error(f"Failed to write drug catalog atomically: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

    if progress_callback:
        progress_callback(total, total, "Tamamlandı")
    return True


if __name__ == "__main__":
    # If run as script, perform inline updates on default path
    default_path = Path(__file__).parent / "drug_catalog.json"
    if not default_path.exists():
        # Fallback to current directory or python_backend/drug_catalog
        default_path = Path("drug_catalog.json")
    
    print(f"Refreshing drug catalog at: {default_path.resolve()}")
    success = refresh_catalog(default_path)
    sys.exit(0 if success else 1)
