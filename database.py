import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import uuid
from supabase import create_client, Client

# --- Configuration ---
# Load from Streamlit Secrets (safe for GitHub)
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
except Exception:
    st.error("Missing secrets! Make sure you have .streamlit/secrets.toml locally or secrets configured in Cloud.")
    st.stop()

@st.cache_resource
def init_connection():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

supabase = init_connection()

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

def get_inventory_df():
    """Fetch all inventory items as a DataFrame."""
    try:
        response = supabase.table("inventory").select("*").order("id").execute()
        data = response.data
        if not data:
            return pd.DataFrame(columns=['id', 'name', 'category', 'maker', 'supplier', 'color', 'barcode', 'quantity', 'price', 'min_threshold'])
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error fetching inventory: {e}")
        return pd.DataFrame()

def get_transactions_df(limit=100):
    """Fetch recent transactions."""
    try:
        response = supabase.table("transactions").select("*").order("timestamp", desc=True).limit(limit).execute()
        data = response.data
        if not data:
            return pd.DataFrame(columns=['id', 'item_id', 'item_name', 'type', 'quantity', 'timestamp', 'note', 'receipt_id'])
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error fetching transactions: {e}")
        return pd.DataFrame()

def add_item(name, category, maker, supplier, color, barcode, quantity, price, min_threshold):
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
        # Unique constraints on DB will handle this, but we can check nicely.
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
            "min_threshold": min_threshold
        }
        
        response = supabase.table("inventory").insert(data).execute()
        new_item = response.data[0]
        
        # Log initial stock
        log_transaction(new_item['id'], new_item['name'], 'INITIAL_STOCK', quantity, 'Initial stock added')
        
        return True, "Item added successfully."
    except Exception as e:
        return False, str(e)

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
        log_transaction(item_id, item_name, transaction_type, abs(change_amount), note, receipt_id, payment_method)
        
        return True, f"Stock updated. New Quantity: {new_qty}"
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

def update_item_details(item_id, name, category, maker, supplier, color, barcode, price, min_threshold):
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
            "min_threshold": min_threshold
        }
        supabase.table("inventory").update(data).eq("id", item_id).execute()
        return True, "Item updated successfully."
    except Exception as e:
        return False, str(e)

def log_transaction(item_id, item_name, type_, quantity, note, receipt_id=None, payment_method="CASH"):
    try:
        data = {
            "item_id": item_id,
            "item_name": item_name,
            "type": type_,
            "quantity": quantity, # Always positive in log
            "note": note,
            "timestamp": datetime.now().isoformat(),
            "receipt_id": receipt_id,
            "payment_method": payment_method
        }
        supabase.table("transactions").insert(data).execute()
    except Exception as e:
        print(f"Failed to log transaction with payment_method: {e}")
        # Fallback: Try without payment_method (in case DB schema isn't updated)
        try:
            del data["payment_method"]
            supabase.table("transactions").insert(data).execute()
        except Exception as e2:
             print(f"Failed to log transaction (fallback): {e2}")

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
            start_date = (datetime.now() - timedelta(days=7)).isoformat()
        elif period == "month":
            start_date = (datetime.now() - timedelta(days=30)).isoformat()
        else:
            start_date = (datetime.now() - timedelta(days=3650)).isoformat()

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
