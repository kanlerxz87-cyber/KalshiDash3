(function(){
  var K=window.Kalshi;
  var cat=document.body.getAttribute("data-category");
  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}
  function fmt$(n){return "$"+Number(n||0).toLocaleString(undefined,{maximumFractionDigits:0});}
  function fmtP(p){return p==null?"—":"$"+Number(p).toFixed(3);}
  function render(list){
    var ranked=K.rankByDollars(list).slice(0,30);
    document.getElementById("statusLine").textContent="Found "+list.length+" open markets in this category. Showing top 30 by dollar volume. Updated "+new Date().toLocaleTimeString();
    if(!ranked.length){ document.getElementById("tableWrap").innerHTML="<p class='muted'>No open markets in this category right now on the "+(K.base()===K.DEMO_BASE?"demo":"production")+" API.</p>"; return; }
    var h="<table><thead><tr><th>#</th><th>Market</th><th>Yes bid/ask</th><th>Last</th><th>Volume ($)</th><th>24h ($)</th><th>Open int.</th><th>Close</th><th>Source</th></tr></thead><tbody>";
    ranked.forEach(function(m,i){
      h+="<tr class='clickable' data-ticker='"+esc(m.ticker)+"'><td>"+(i+1)+"</td><td><strong>"+esc(m.title||m.ticker)+"</strong><br><span class='muted small'>"+esc(m.ticker)+"</span></td><td>"+fmtP(m.yes_bid)+" / "+fmtP(m.yes_ask)+"</td><td>"+fmtP(m.last_price)+"</td><td>"+fmt$(m.volume)+"</td><td>"+fmt$(m.volume_24h)+"</td><td>"+Number(m.open_interest||0).toLocaleString()+"</td><td class='small'>"+esc(m.close_time||"")+"</td><td class='small'><a href='"+K.marketUrl(m.ticker)+"' target='_blank' rel='noopener'>Kalshi</a> · <a href='"+K.apiUrl("/markets/"+encodeURIComponent(m.ticker))+"' target='_blank' rel='noopener'>API</a></td></tr>";
    });
    h+="</tbody></table>";
    document.getElementById("tableWrap").innerHTML=h;
    Array.prototype.forEach.call(document.querySelectorAll("#tableWrap tr[data-ticker]"),function(tr){
      tr.addEventListener("click",function(){ location.href="dashboard.html?ticker="+encodeURIComponent(tr.getAttribute("data-ticker")); });
    });
  }
  document.getElementById("statusLine").textContent="Loading…";
  K.fetchAllOpenMarkets(10).then(function(all){
    var list=all.filter(function(m){return K.classify(m)===cat;});
    list.forEach(function(m){K.trackMarket(m);});
    render(list);
  }).catch(function(e){
    document.getElementById("tableWrap").innerHTML="<div class='notice'>Load failed: "+esc(String(e))+"</div>";
  });
  setInterval(function(){
    K.fetchAllOpenMarkets(10).then(function(all){
      var list=all.filter(function(m){return K.classify(m)===cat;});
      render(list);
    }).catch(function(){});
  }, 30000);
})();
