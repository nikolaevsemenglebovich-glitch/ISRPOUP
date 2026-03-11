let cart = {};

function showToastMessage(text, success = true) {
    let toast = document.getElementById("toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "toast";
        document.body.appendChild(toast);
    }

    toast.className = success ? "toast toast-success" : "toast toast-error";
    toast.innerText = text;

    // Анимация: сначала прозрачный → затем появление
    setTimeout(() => toast.classList.add("show"), 10);

    setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}
    }
    toast.innerText = text;
    toast.style.display = 'block';
    toast.style.background = success ? '#2ecc71' : '#e74c3c';
    toast.style.color = '#fff';
    toast.style.padding = '12px 18px';
    toast.style.borderRadius = '8px';
    toast.style.position = 'fixed';
    toast.style.right = '30px';
    toast.style.bottom = '30px';
    toast.style.zIndex = '9999';
    setTimeout(()=>{ toast.style.display = 'none'; }, 3000);
}

function addToCart(id, name, price){
    if(cart[id]) cart[id].quantity++;
    else cart[id] = {name:name, price:price, quantity:1};
    renderCart();
    showToastMessage('Добавлено в корзину', true);
}

function renderCart(){
    const ul = document.getElementById('cart-items');
    if(!ul) return;
    ul.innerHTML = '';
    let total = 0;
    for(let id in cart){
        const item = cart[id];
        total += item.price * item.quantity;
        ul.innerHTML += `<li>${item.name} x ${item.quantity} <button onclick="removeItem('${id}')">❌</button></li>`;
    }
    const totalEl = document.getElementById('total');
    if(totalEl) totalEl.innerText = total;
}

function removeItem(id){
    delete cart[id];
    renderCart();
}

function checkout(){
    if(Object.keys(cart).length === 0){
        showToastMessage("Корзина пуста", false);
        return;
    }

    fetch("/create_order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cart)
    })
    .then(res => res.json())
    .then(data => {
        if(data.ok){
            showToastMessage(data.message, true);
            cart = {};
            renderCart();
        } else {
            showToastMessage(data.message || 'Ошибка создания заказа', false);
        }
    })
    .catch(err => {
        showToastMessage('Сетевая ошибка', false);
        console.error(err);
    });
}
