(function(){
  var K=window.Kalshi, Charts=window.Charts;
  var allMarkets=[], selected=null, livePoints=[], pollTimer=null, sampleTimer=null;
  function $(id){return document.getElementById(id);}
  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}
  function fmt$(n){return "$"+Number(n||0).toLocaleString(undefined,{maximumFractionDigits:0});}
  function fmtP(p){return p==null?"—":"$"+Number(p).toFixed(3);}
  function fmtTime(t){return t?new Date(t).toLocaleString():"—";}

  function filtered(){
    var cat=$("catFilter").value, q=$("search").value.trim().toLowerCase(), sort=$("sortBy").value;
    var list=allMarkets.filter(function(m){
      if(cat && K.classify(m)!==cat) return false;
      if(!cat && !K.classify(m)) return false;
      if(q && (m.ticker.toLowerCase().indexOf(q)===-1 && (m.title||"").toLowerCase().indexOf(q)===-1)) return false;
      return true;
    });
    if(sort==="volume_24h") list.sort(function(a,b){return b.volume_24h-a.volume_24h;});
    else if(sort==="open_interest") list.sort(function(a,b){return b.open_interest-a.open_interest;});
    else if(sort==="close_time") list.sort(function(a,b){return (a.close_time||"").localeCompare(b.close_time||"");});
    else list=K.rankByDollars(list);
    return list;
  }

  function renderTable(){
    var list=filtered().slice(0,50);
    $("statusLine").textContent="Showing "+list.length+" of "+allMarkets.length+" open markets (5 categories). Base: "+K.base()+" · Updated "+new Date().toLocaleTimeString();
    if(!list.length){ $("tableWrap").innerHTML="<p class='muted'>No markets match. Try clearing filters.</p>"; return; }
    var h="<table><thead><tr><th>#</th><th>Market</th><th>Cat.</th><th>Yes bid/ask</th><th>Last</th><th>Volume ($)</th><th>24h ($)</th><th>Open int.</th><th>Close</th><th>Status / Result</th><th>Source</th></tr></thead><tbody>";
    list.forEach(function(m,i){
      var res=m.result?("<span class='pill "+(m.result==="yes"?"yes":"no")+"'>"+esc(m.result.toUpperCase())+"</span>"):"<span class='pill'>open</span>";
      h+="<tr class='clickable' data-ticker='"+esc(m.ticker)+"'><td>"+(i+1)+"</td><td><strong>"+esc(m.title||m.ticker)+"</strong><br><span class='muted small'>"+esc(m.ticker)+"</span></td><td>"+esc(K.classify(m)||"—")+"</td><td>"+fmtP(m.yes_bid)+" / "+fmtP(m.yes_ask)+"</td><td>"+fmtP(m.last_price)+"</td><td>"+fmt$(m.volume)+"</td><td>"+fmt$(m.volume_24h)+"</td><td>"+Number(m.open_interest||0).toLocaleString()+"</td><td class='small'>"+esc(m.close_time||"")+"</td><td>"+res+"</td><td class='small'><a href='"+K.marketUrl(m.ticker)+"' target='_blank' rel='noopener'>Kalshi</a> · <a href='"+K.apiUrl("/markets/"+encodeURIComponent(m.ticker))+"' target='_blank' rel='noopener'>API</a></td></tr>";
    });
    h+="</tbody></table>";
    $("tableWrap").innerHTML=h;
    Array.prototype.forEach.call(document.querySelectorAll("#tableWrap tr[data-ticker]"),function(tr){
      tr.addEventListener("click",function(){ selectMarket(tr.getAttribute("data-ticker")); });
    });
  }

  function loadAll(){
    $("statusLine").textContent="Loading…";
    K.fetchAllOpenMarkets(10).then(function(all){
      allMarkets=all;
      // auto-track top 10 by dollars
      K.rankByDollars(all.filter(function(m){return K.classify(m);})).slice(0,10).forEach(function(m){ K.trackMarket(m); });
      renderTable();
      // check tracked for resolution
      checkTracked();
    }).catch(function(e){
      $("tableWrap").innerHTML="<div class='notice'>Load failed: "+esc(String(e))+". <button onclick='location.reload()'>Retry</button></div>";
    });
  }

  function checkTracked(){
    var t=K.loadTracked();
    Object.keys(t).forEach(function(ticker){
      var entry=t[ticker];
      if(entry.result==="yes"||entry.result==="no") return;
      K.getMarket(ticker).then(function(m){
        K.trackMarket(m);
        if(K.isResolved(m) && m.result){
          var tt=K.loadTracked(); tt[ticker].result=m.result; tt[ticker].resolved_at=new Date().toISOString(); tt[ticker].status=m.status; K.saveTracked(tt);
        }
      }).catch(function(){});
    });
  }

  function selectMarket(ticker){
    $("tickerInput").value=ticker;
    loadDetail(ticker);
  }

  function loadDetail(ticker){
    if(!ticker) return;
    livePoints=[];
    K.getMarket(ticker).then(function(m){
      selected=m; K.trackMarket(m);
      var res=m.result?("<span class='pill "+(m.result==="yes"?"yes":"no")+"'>"+esc(m.result.toUpperCase())+"</span>"):"<span class='pill'>open</span>";
      $("detail").innerHTML="<div class='card'><h3>"+esc(m.title||m.ticker)+"</h3><p class='small muted'>"+esc(m.ticker)+" · "+esc(m.event_ticker||"")+" · "+esc(m.series_ticker||"")+"</p><p>Yes <strong>"+fmtP(m.yes_bid)+"</strong> / Ask <strong>"+fmtP(m.yes_ask)+"</strong> · Last <strong>"+fmtP(m.last_price)+"</strong> · Volume <strong>"+fmt$(m.volume)+"</strong> · Open int. <strong>"+Number(m.open_interest||0).toLocaleString()+"</strong> · Close <strong>"+esc(m.close_time||"—")+"</strong> · "+res+"</p><p class='small'><a href='"+K.marketUrl(m.ticker)+"' target='_blank' rel='noopener'>Open on Kalshi</a> · <a href='"+K.apiUrl("/markets/"+encodeURIComponent(m.ticker))+"' target='_blank' rel='noopener'>API JSON</a> · <a href='"+K.apiUrl("/markets/"+encodeURIComponent(m.ticker)+"/orderbook")+"' target='_blank' rel='noopener'>Orderbook JSON</a></p></div>";
      refreshChart(); refreshBook(); refreshTrades();
      startSampling();
    }).catch(function(e){
      $("detail").innerHTML="<div class='notice'>Could not load "+esc(ticker)+": "+esc(String(e))+"</div>";
    });
  }

  function refreshChart(){
    if(!selected) return;
    var win=Number($("windowSel").value);
    var now=Date.now();
    if(win<=60){
      // seconds view: use live samples only
      Charts.drawLine($("priceChart"), livePoints, {title:"Live samples (seconds)"});
      return;
    }
    var period = win<=3600 ? 1 : 60; // 1-min bars up to 1h, else hourly
    var startTs=Math.floor((now-win*1000)/1000), endTs=Math.floor(now/1000);
    var series=selected.series_ticker||"";
    if(!series){ Charts.drawLine($("priceChart"), livePoints, {title:"No series_ticker — live samples only"}); return; }
    K.getCandlesticks(series, selected.ticker, startTs, endTs, period).then(function(d){
      var candles=d.candlesticks||d.candles||[];
      var pts=candles.map(function(c){
        var t=(c.end_period_ts||c.start_period_ts||c.timestamp||0)*1000;
        var p=c.yes_bid&&c.yes_bid.close_dollars!==undefined?Number(c.yes_bid.close_dollars):(c.close_dollars!==undefined?Number(c.close_dollars):(c.yes_close!==undefined?Number(c.yes_close)/100:null));
        return p==null?null:{t:t, price:p};
      }).filter(Boolean);
      // merge live samples
      pts=pts.concat(livePoints).sort(function(a,b){return a.t-b.t;});
      if(pts.length<2 && selected.last_price!=null){
        pts=[{t:now-win*1000, price:selected.last_price},{t:now, price:selected.last_price}];
      }
      Charts.drawLine($("priceChart"), pts, {title:"Candlesticks ("+(period===1?"1-min":"1-hour")+") + live"});
    }).catch(function(){
      Charts.drawLine($("priceChart"), livePoints, {title:"Candlesticks unavailable — live samples"});
    });
  }

  function refreshBook(){
    if(!selected) return;
    K.getOrderbook(selected.ticker, 20).then(function(ob){
      Charts.drawLiquidity($("liqChart"), ob);
      var yes=ob.yes_dollars||[], no=ob.no_dollars||[];
      var h="<table><thead><tr><th>Side</th><th>Price ($)</th><th>Contracts available</th><th>Implied opposite</th></tr></thead><tbody>";
      yes.slice().reverse().forEach(function(l){ h+="<tr><td>YES bid</td><td>"+esc(l[0])+"</td><td>"+esc(l[1])+"</td><td>NO ask $"+(1-parseFloat(l[0])).toFixed(4)+"</td></tr>"; });
      no.slice().reverse().forEach(function(l){ h+="<tr><td>NO bid</td><td>"+esc(l[0])+"</td><td>"+esc(l[1])+"</td><td>YES ask $"+(1-parseFloat(l[0])).toFixed(4)+"</td></tr>"; });
      h+="</tbody></table><p class='small muted'>Kalshi orderbook returns bids only; asks are implied as $1 − opposite bid. Source: <a href='https://docs.kalshi.com/getting_started/orderbook_responses.md' target='_blank' rel='noopener'>Orderbook docs</a>.</p>";
      $("bookTable").innerHTML=h;
    }).catch(function(e){ $("bookTable").innerHTML="<p class='muted'>Orderbook failed: "+esc(String(e))+"</p>"; });
  }

  function refreshTrades(){
    if(!selected) return;
    K.getTrades(selected.ticker, 20).then(function(d){
      var trades=d.trades||[];
      if(!trades.length){ $("tradesTable").innerHTML="<p class='muted'>No recent trades.</p>"; return; }
      var h="<table><thead><tr><th>Time</th><th>Price ($)</th><th>Contracts</th><th>Taker side</th></tr></thead><tbody>";
      trades.forEach(function(t){
        var price=t.yes_price_dollars!==undefined?t.yes_price_dollars:(t.yes_price!==undefined?(t.yes_price/100):"—");
        var count=t.count_fp!==undefined?t.count_fp:(t.count||"—");
        var time=t.created_time||t.timestamp||"";
        h+="<tr><td class='small'>"+esc(time)+"</td><td>"+esc(price)+"</td><td>"+esc(count)+"</td><td>"+esc(t.taker_side||t.taker_outcome_side||"—")+"</td></tr>";
      });
      h+="</tbody></table>";
      $("tradesTable").innerHTML=h;
    }).catch(function(e){ $("tradesTable").innerHTML="<p class='muted'>Trades failed: "+esc(String(e))+"</p>"; });
  }

  function startSampling(){
    if(sampleTimer) clearInterval(sampleTimer);
    sampleTimer=setInterval(function(){
      if(!selected) return;
      K.getMarket(selected.ticker).then(function(m){
        selected=m;
        if(m.last_price!=null){
          livePoints.push({t:Date.now(), price:m.last_price});
          if(livePoints.length>600) livePoints.shift();
        }
        if(Number($("windowSel").value)<=60) Charts.drawLine($("priceChart"), livePoints, {title:"Live samples (seconds)"});
      }).catch(function(){});
    }, 5000);
  }

  $("refreshBtn").addEventListener("click", loadAll);
  $("catFilter").addEventListener("change", renderTable);
  $("search").addEventListener("input", renderTable);
  $("sortBy").addEventListener("change", renderTable);
  $("loadBtn").addEventListener("click", function(){ loadDetail($("tickerInput").value.trim()); });
  $("trackBtn").addEventListener("click", function(){
    var t=$("tickerInput").value.trim(); if(!t) return;
    K.getMarket(t).then(function(m){ K.trackMarket(m); alert("Tracking "+t+" until resolved. See Resolved page."); }).catch(function(e){ alert(String(e)); });
  });
  $("windowSel").addEventListener("change", refreshChart);

  var params=new URLSearchParams(location.search);
  var initTicker=params.get("ticker");
  loadAll();
  if(initTicker) loadDetail(initTicker);
  pollTimer=setInterval(loadAll, 30000);
})();
