import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import uuid
import pytz
from supabase import create_client, Client

def get_eastern_time():
    """Returns current time in US/Eastern timezone."""
    return datetime.now(pytz.timezone('US/Eastern'))

# --- Configuration ---
# Load from Streamlit Secrets (safe for GitHub)
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except Exception:
    st.error("Missing secrets! Make sure you have .streamlit/secrets.toml locally or secrets configured in Cloud.")
    st.stop()

@st.cache_resource(ttl=3600)
def init_connection():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

supabase = init_connection()

# --- Retry Logic for Stability ---
import time
from functools import wraps

def retry_db(max_retries=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        print(f"DB Error after {max_retries} retries: {e}")
                        raise e
                    time.sleep(delay * (i + 1)) # Exponential-ish backoff
        return wrapper
    return decorator

# --- Settings ---
def init_settings():
    """Ensure default settings exist."""
    try:
        # Check if settings exist, if not insert defaults
        defaults = [
            {"key": "global_password", "value": "0000"},
            {"key": "admin_password", "value": "0000"}
        ]
        
        for d in defaults:
            existing = supabase.table("system_settings").select("key").eq("key", d["key"]).execute()
            if not existing.data:
                supabase.table("system_settings").insert(d).execute()
                
    except Exception as e:
        print(f"Settings init failed (maybe table doesn't exist yet): {e}")

def get_setting(key, default=None):
    """Fetch a setting value by key."""
    try:
        response = supabase.table("system_settings").select("value").eq("key", key).single().execute()
        if response.data:
            return response.data['value']
        return default
    except Exception as e:
        return default

def set_setting(key, value):
    """Update or insert a setting."""
    try:
        data = {"key": key, "value": str(value)}
        supabase.table("system_settings").upsert(data).execute()
        return True, "Setting saved."
    except Exception as e:
        return False, str(e)

if supabase:
    init_settings()

# --- Core Functions ---

@retry_db(max_retries=3)
def get_inventory_df():
    """Fetch all inventory items as a DataFrame."""
    try:
        response = supabase.table("inventory").select("*").order("id").execute()
        data = response.data
        if not data:
            return pd.DataFrame(columns=['id', 'name', 'category', 'maker', 'supplier', 'color', 'barcode', 'quantity', 'price', 'min_threshold', 'sale_percent', 'bogo'])
        df = pd.DataFrame(data)
        # Ensure promo columns exist even if DB hasn't been updated yet
        if 'sale_percent' not in df.columns:
            df['sale_percent'] = 0
        if 'bogo' not in df.columns:
            df['bogo'] = False
        df['sale_percent'] = df['sale_percent'].fillna(0).astype(int)
        df['bogo'] = df['bogo'].fillna(False).astype(bool)
        return df
    except Exception as e:
        st.error(f"Error fetching inventory: {e}")
        return pd.DataFrame()

@retry_db(max_retries=3)
def get_transactions_df(limit=100):
    """Fetch recent transactions."""
    try:
        response = supabase.table("transactions").select("*").order("timestamp", desc=True).limit(limit).execute()
        data = response.data
        if not data:
            return pd.DataFrame(columns=['id', 'item_id', 'item_name', 'type', 'quantity', 'timestamp', 'note', 'receipt_id', 'payment_method'])
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error fetching transactions: {e}")
        return pd.DataFrame()

@retry_db(max_retries=3)
def add_item(name, category, maker, supplier, color, barcode, quantity, price, min_threshold, sale_percent=0, bogo=False):
    """Add a new item to the inventory."""
    try:
        # Treat empty barcode as None to avoid unique constraint violation on empty strings
        if not barcode:
            barcode = None
            
        # Enforce Uppercase for normalized fields
        category = category.upper() if category else category
        maker = maker.upper() if maker else maker
        supplier = supplier.upper() if supplier else supplier

        # Check if item exists (by name or barcode)
        existing = supabase.table("inventory").select("id").eq("name", name).execute()
        if existing.data:
            return False, f"Item '{name}' already exists."

        if barcode:
            existing_bc = supabase.table("inventory").select("id").eq("barcode", barcode).execute()
            if existing_bc.data:
                 return False, f"Barcode '{barcode}' already exists."

        data = {
            "name": name,
            "category": category,
            "maker": maker,
            "supplier": supplier,
            "color": color,
            "barcode": barcode,
            "quantity": quantity,
            "price": price,
            "min_threshold": min_threshold,
            "sale_percent": int(sale_percent),
            "bogo": bool(bogo)
        }
        
        response = supabase.table("inventory").insert(data).execute()
        new_item = response.data[0]
        
        # Log initial stock
        log_transaction(new_item['id'], new_item['name'], 'INITIAL_STOCK', quantity, 'Initial stock added')
        
        return True, "Item added successfully."
    except Exception as e:
        return False, str(e)

@retry_db(max_retries=3)
def update_stock(item_id, item_name, change_amount, transaction_type, note="", receipt_id=None, payment_method="CASH"):
    """Update stock level and log transaction."""
    try:
        # 1. Get current stock
        res = supabase.table("inventory").select("quantity").eq("id", item_id).single().execute()
        if not res.data:
            return False, "Item not found."
            
        current_qty = res.data['quantity']
        new_qty = current_qty + change_amount
        
        if new_qty < 0:
            return False, f"Insufficient stock for {item_name}."
            
        # 2. Update Inventory
        supabase.table("inventory").update({"quantity": new_qty}).eq("id", item_id).execute()
        
        # 3. Log Transaction
        log_success, log_err = log_transaction(item_id, item_name, transaction_type, abs(change_amount), note, receipt_id, payment_method)
        
        msg = f"Stock updated. New Quantity: {new_qty}"
        if not log_success:
            msg += f" (⚠️ History Log Failed: {log_err})"
            
        return True, msg
    except Exception as e:
        return False, str(e)

def process_batch_transaction(cart_items, transaction_type="SALE", payment_method="CASH"):
    """
    Process multiple items in a single transaction (Receipt).
    cart_items: List of dicts {'id', 'name', 'qty', 'note'}
    """
    try:
        receipt_id = str(uuid.uuid4())
        errors = []
        
        for item in cart_items:
            # Determine change amount (Negative for SALE)
            change = -item['qty'] if transaction_type == "SALE" else item['qty']
            
            # Special case for RESTOCK mode - positive change, same transaction type name or different?
            # User passed "RESTOCK" as transaction_type for restocks.
            if transaction_type == "RESTOCK":
                 change = item['qty']
            
            success, msg = update_stock(
                item['id'], 
                item['name'], 
                change, 
                transaction_type, 
                item.get('note', ''), 
                receipt_id,
                payment_method
            )
            
            if not success:
                errors.append(f"Failed {item['name']}: {msg}")
        
        if errors:
            return False, "Some items failed: " + "; ".join(errors)
            
        return True, receipt_id
        
    except Exception as e:
        return False, str(e)

@retry_db(max_retries=3)
def update_item_details(item_id, name, category, maker, supplier, color, barcode, price, min_threshold, sale_percent=0, bogo=False):
    try:
        # Treat empty barcode as None
        if not barcode:
            barcode = None
            
        # Enforce Uppercase
        category = category.upper() if category else category
        maker = maker.upper() if maker else maker
        supplier = supplier.upper() if supplier else supplier
            
        data = {
            "name": name,
            "category": category,
            "maker": maker,
            "supplier": supplier,
            "color": color,
            "barcode": barcode,
            "price": price,
            "min_threshold": min_threshold,
            "sale_percent": int(sale_percent),
            "bogo": bool(bogo)
        }
        supabase.table("inventory").update(data).eq("id", item_id).execute()
        return True, "Item updated successfully."
    except Exception as e:
        return False, str(e)

@retry_db(max_retries=3)
def log_transaction(item_id, item_name, type_, quantity, note, receipt_id=None, payment_method="CASH"):
    try:
        data = {
            "item_id": item_id,
            "item_name": item_name,
            "type": type_,
            "quantity": quantity, # Always positive in log
            "note": note,
            "timestamp": get_eastern_time().isoformat(),
            "receipt_id": receipt_id,
            "payment_method": payment_method
        }
        supabase.table("transactions").insert(data).execute()
        return True, "Logged"
    except Exception as e:
        # If this fails, it is likely because the 'payment_method' or 'receipt_id' columns 
        # are missing from the Supabase table.
        print(f"⚠️ Failed to log transaction with payment_method: {e}")
        try:
            # Fallback: Try without the newer columns
            data.pop("payment_method", None)
            data.pop("receipt_id", None)
            supabase.table("transactions").insert(data).execute()
            return True, f"Logged (Fallback - Missing DB Column? Error: {e})"
        except Exception as e2:
             print(f"CRITICAL: Failed to log transaction (fallback): {e2}")
             return False, f"Log Failed: {e2}"

def delete_item(item_id):
    """Delete item and its transactions."""
    try:
        # Delete transactions first (foreign key might cascade but let's be safe)
        supabase.table("transactions").delete().eq("item_id", item_id).execute()
        # Delete item
        supabase.table("inventory").delete().eq("id", item_id).execute()
        return True, "Item and history deleted."
    except Exception as e:
        return False, str(e)

def get_top_selling_items(period="week", limit=10):
    """
    Get top selling items.
    For this MVP, we'll fetch sales and process in Python, or use a simple query.
    """
    try:
        if period == "week":
            start_date = (get_eastern_time() - timedelta(days=7)).isoformat()
        elif period == "month":
            start_date = (get_eastern_time() - timedelta(days=30)).isoformat()
        else:
            start_date = (get_eastern_time() - timedelta(days=3650)).isoformat()

        # Fetch sales
        # To do this efficiently in Supabase/PostgREST without a stored proc is tricky for aggregation.
        # We will fetch raw sales rows and aggregate in Pandas for now (fast enough for <10k rows).
        
        response = supabase.table("transactions")\
            .select("item_name, quantity, item_id")\
            .eq("type", "SALE")\
            .gte("timestamp", start_date)\
            .execute()
            
        sales = response.data
        if not sales:
            return pd.DataFrame()
            
        df = pd.DataFrame(sales)
        
        # We also need price to calculate revenue
        # Fetch inventory prices (simplified: fetch all prices)
        inv_res = supabase.table("inventory").select("id, price").execute()
        inv_map = {row['id']: row['price'] for row in inv_res.data}
        
        df['price'] = df['item_id'].map(inv_map).fillna(0)
        df['revenue'] = df['quantity'] * df['price']
        
        grouped = df.groupby('item_name').agg({
            'quantity': 'sum',
            'revenue': 'sum'
        }).reset_index()
        
        grouped = grouped.rename(columns={'quantity': 'Total Sold', 'revenue': 'Revenue', 'item_name': 'Item Name'})
        grouped = grouped.sort_values(by='Total Sold', ascending=False).head(limit)
        
        return grouped
        
    except Exception as e:
        print(f"Error getting top items: {e}")
        return pd.DataFrame()

# --- Customer Display / Realtime Sync ---
def update_live_cart(cart_data):
    try:
        import json
        json_str = json.dumps(cart_data)
        # Reuse existing set_setting function
        supabase.table('system_settings').upsert({'key': 'live_cart_data', 'value': json_str}).execute()
        return True
    except Exception as e:
        print(f'Failed to update live cart: {e}')
        return False

def get_live_cart():
    try:
        import json
        res = supabase.table('system_settings').select('value').eq('key', 'live_cart_data').single().execute()
        if not res.data:
            return None
        val = res.data['value']
        if not val:
            return None
        return json.loads(val)
    except Exception as e:
        print(f'Failed to get live cart: {e}')
        return None

@retry_db(max_retries=3)
def clear_live_cart():
    empty_cart = {'items': [], 'subtotal': 0, 'discount': 0, 'total': 0}
    print("Clearing live cart...")
    return update_live_cart(empty_cart)

