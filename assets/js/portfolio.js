(function(){
  var K=window.Kalshi;
  function $(id){return document.getElementById(id);}
  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}
  function money(cents){ return "$"+(Number(cents||0)/100).toFixed(2); }
  function refreshConn(){
    var k=K.getStoredKey();
    $("connStatus").textContent=k.id?("Key stored: "+k.id+" (browser only)."):"No key stored.";
    if(k.id) $("keyId").value=k.id;
  }
  $("saveKeyBtn").addEventListener("click", function(){
    var id=$("keyId").value.trim(), pem=$("keyPem").value.trim();
    if(!id||!pem){ alert("Enter both key ID and PEM."); return; }
    K.storeKey(id,pem); refreshConn(); alert("Saved in this browser only.");
  });
  $("clearKeyBtn").addEventListener("click", function(){ K.clearKey(); $("keyPem").value=""; refreshConn(); });
  refreshConn();

  function loadPortfolio(){
    $("balanceWrap").innerHTML="<p class='muted'>Loading…</p>";
    K.authedFetch("/portfolio/balance","GET").then(function(d){
      var bal=d.balance!==undefined?d.balance:(d.balance_cents!==undefined?d.balance_cents:null);
      var pv=d.portfolio_value!==undefined?d.portfolio_value:null;
      $("balanceWrap").innerHTML="<div class='grid'><div class='card'><div class='muted small'>Cash balance</div><div class='big'>"+(bal==null?"—":money(bal))+"</div></div><div class='card'><div class='muted small'>Portfolio value</div><div class='big'>"+(pv==null?"—":money(pv))+"</div></div></div><p class='small muted'>Source: <a href='"+K.apiUrl("/portfolio/balance")+"' target='_blank' rel='noopener'>GET /portfolio/balance</a></p>";
    }).catch(function(e){ $("balanceWrap").innerHTML="<div class='notice'>Balance failed: "+esc(String(e))+"</div>"; });

    K.authedFetch("/portfolio/positions?limit=100","GET").then(function(d){
      var pos=d.market_positions||d.positions||[];
      if(!pos.length){ $("positionsWrap").innerHTML="<p class='muted'>No open positions.</p>"; return; }
      var h="<table><thead><tr><th>Ticker</th><th>Position</th><th>Total traded</th><th>Realized P&L</th><th>Fees paid</th></tr></thead><tbody>";
      pos.forEach(function(p){
        h+="<tr><td>"+esc(p.ticker||"")+"</td><td>"+esc(p.position!==undefined?p.position:(p.yes_count||""))+"</td><td>"+esc(p.total_traded!==undefined?money(p.total_traded):"—")+"</td><td>"+esc(p.realized_pnl!==undefined?money(p.realized_pnl):"—")+"</td><td>"+esc(p.fees_paid!==undefined?money(p.fees_paid):"—")+"</td></tr>";
      });
      h+="</tbody></table>";
      $("positionsWrap").innerHTML=h;
    }).catch(function(e){ $("positionsWrap").innerHTML="<p class='muted'>Positions failed: "+esc(String(e))+"</p>"; });

    K.authedFetch("/portfolio/fills?limit=200","GET").then(function(d){
      renderFills(d.fills||d||[]);
    }).catch(function(e){ $("fillsWrap").innerHTML="<p class='muted'>Fills failed: "+esc(String(e))+"</p>"; });

    K.authedFetch("/portfolio/settlements?limit=200","GET").then(function(d){
      renderSettlements(d.settlements||d||[]);
    }).catch(function(e){ $("settlementsWrap").innerHTML="<p class='muted'>Settlements failed: "+esc(String(e))+"</p>"; });
  }
  $("loadBtn").addEventListener("click", loadPortfolio);

  function fillPrice(f){
    if(f.yes_price_fixed!==undefined) return Number(f.yes_price_fixed);
    if(f.yes_price!==undefined) return Number(f.yes_price)/100;
    if(f.price!==undefined) return Number(f.price);
    return null;
  }
  function fillCount(f){ return f.count_fp!==undefined?Number(f.count_fp):(f.count||0); }

  function renderFills(fills){
    if(!fills.length){ $("fillsWrap").innerHTML="<p class='muted'>No fills yet. Place a demo trade above.</p>"; return; }
    // Categorize
    var byCat={}, bySide={}, taker=0, maker=0, totalNotional=0;
    fills.forEach(function(f){
      var m={ticker:f.ticker||"", series_ticker:f.series_ticker||"", title:f.ticker||""};
      var cat=K.classify(m)||"other";
      byCat[cat]=(byCat[cat]||0)+1;
      var side=(f.side||f.outcome_side||"unknown").toString().toLowerCase();
      bySide[side]=(bySide[side]||0)+1;
      if(f.is_taker) taker++; else maker++;
      var p=fillPrice(f), c=fillCount(f);
      if(p!=null) totalNotional+=p*c;
    });
    var h="<div class='grid'>";
    h+="<div class='card'><div class='muted small'>Total fills</div><div class='big'>"+fills.length+"</div></div>";
    h+="<div class='card'><div class='muted small'>Notional traded ($)</div><div class='big'>$"+totalNotional.toFixed(2)+"</div></div>";
    h+="<div class='card'><div class='muted small'>Taker / Maker</div><div class='big'>"+taker+" / "+maker+"</div></div>";
    h+="</div>";
    h+="<h3>Fills by category</h3><table><thead><tr><th>Category</th><th>Fills</th></tr></thead><tbody>";
    Object.keys(byCat).sort(function(a,b){return byCat[b]-byCat[a];}).forEach(function(c){ h+="<tr><td>"+esc(c)+"</td><td>"+byCat[c]+"</td></tr>"; });
    h+="</tbody></table>";
    h+="<h3>Fills by side</h3><table><thead><tr><th>Side</th><th>Fills</th></tr></thead><tbody>";
    Object.keys(bySide).forEach(function(s){ h+="<tr><td>"+esc(s)+"</td><td>"+bySide[s]+"</td></tr>"; });
    h+="</tbody></table>";
    h+="<h3>All fills</h3><table><thead><tr><th>Time</th><th>Ticker</th><th>Side</th><th>Action</th><th>Price ($)</th><th>Count</th><th>Taker?</th></tr></thead><tbody>";
    fills.slice(0,100).forEach(function(f){
      var p=fillPrice(f);
      h+="<tr><td class='small'>"+esc(f.created_time||f.timestamp||"")+"</td><td>"+esc(f.ticker||"")+"</td><td>"+esc(f.side||f.outcome_side||"")+"</td><td>"+esc(f.action||"")+"</td><td>"+(p==null?"—":p.toFixed(4))+"</td><td>"+esc(fillCount(f))+"</td><td>"+esc(f.is_taker?"yes":"no")+"</td></tr>";
    });
    h+="</tbody></table>";
    h+="<h3>Strategy hints (suggestions only)</h3><ul>";
    h+="<li>If one category dominates fills, compare its win rate (settlements below) before adding size — concentration risk.</li>";
    h+="<li>High taker share = paying spread for immediacy; consider limit/maker orders in wide-spread markets.</li>";
    h+="<li>Review average entry price vs settlement outcome per category to spot systematic overpaying.</li>";
    h+="</ul>";
    $("fillsWrap").innerHTML=h;
  }

  function renderSettlements(setts){
    if(!setts.length){ $("settlementsWrap").innerHTML="<p class='muted'>No settlements yet.</p>"; return; }
    var wins=0, losses=0, pnl=0;
    setts.forEach(function(s){
      var rev=Number(s.revenue||0), cost=Number(s.yes_total_cost||0)+Number(s.no_total_cost||0);
      var p=rev-cost; pnl+=p; if(p>0) wins++; else if(p<0) losses++;
    });
    var h="<div class='grid'><div class='card'><div class='muted small'>Settled markets</div><div class='big'>"+setts.length+"</div></div><div class='card'><div class='muted small'>Wins / Losses</div><div class='big'>"+wins+" / "+losses+"</div></div><div class='card'><div class='muted small'>Realized P&L (settlements)</div><div class='big'>"+money(pnl)+"</div></div></div>";
    h+="<table><thead><tr><th>Ticker</th><th>Result</th><th>YES count</th><th>NO count</th><th>Revenue</th><th>Settled at</th></tr></thead><tbody>";
    setts.slice(0,100).forEach(function(s){
      h+="<tr><td>"+esc(s.ticker||"")+"</td><td>"+esc(s.market_result||s.result||"")+"</td><td>"+esc(s.yes_count||0)+"</td><td>"+esc(s.no_count||0)+"</td><td>"+money(s.revenue||0)+"</td><td class='small'>"+esc(s.settled_time||"")+"</td></tr>";
    });
    h+="</tbody></table>";
    $("settlementsWrap").innerHTML=h;
  }

  $("tradeBtn").addEventListener("click", function(){
    var ticker=$("tradeTicker").value.trim();
    var side=$("tradeSide").value, action=$("tradeAction").value;
    var count=String($("tradeCount").value||"1"), price=Number($("tradePrice").value);
    if(!ticker){ alert("Enter a ticker."); return; }
    if(!(price>=0.01&&price<=0.99)){ alert("Price must be 0.01–0.99."); return; }
    var clientOrderId=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+"-"+Math.random();
    // New event-orders endpoint (see Quick Start). Legacy /portfolio/orders is also supported by Kalshi; we use events/orders per current docs.
    var body={ ticker:ticker, side:(action==="buy"?"bid":"ask"), count:count, price:price.toFixed(4), time_in_force:"good_till_canceled", self_trade_prevention_type:"taker_at_cross", client_order_id:clientOrderId };
    // Map outcome side: Kalshi event orders use side bid/ask + outcome_side in newer docs; include both for compatibility.
    body.outcome_side=side;
    $("tradeResult").style.display="block"; $("tradeResult").textContent="Placing demo order…";
    K.authedFetch("/portfolio/events/orders","POST",body).then(function(d){
      $("tradeResult").textContent=JSON.stringify(d,null,2);
      loadPortfolio();
    }).catch(function(e){
      $("tradeResult").textContent="Order failed: "+String(e)+"\n"+(e.data?JSON.stringify(e.data,null,2):"");
    });
  });
})();
