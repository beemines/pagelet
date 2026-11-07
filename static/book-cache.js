/* Public bibliographic data only. Auth, quota and download jobs always stay live. */
(function (root) {
  'use strict';
  const PREFIX='shiye-books-v1:';
  const FIELDS=['id','name','publisher','year','language','extension','size','rating','quality','isbn','isbn_10','isbn_13','edition','pages','categories','description'];
  function safeUrl(value,cover=false) {
    if(typeof value!=='string')return '';
    if(cover && /^\/static\/covers\/home-[a-z0-9-]+\.(jpg|png|webp)$/.test(value))return value;
    try {
      const url=new URL(value);
      if(url.protocol!=='https:' || url.username || url.password || (url.port && url.port!=='443'))return '';
      if(cover) return ['cdn-zlib.sk','zlibcdn2.com'].some(host=>url.hostname===host||url.hostname.endsWith('.'+host))?url.origin+url.pathname:'';
      return url.pathname.startsWith('/book/')?url.origin+url.pathname:'';
    }catch{return '';}
  }
  function publicBook(value) {
    if(!value || typeof value!=='object' || !/^\d+:[a-z0-9]+$/i.test(value.id||''))return null;
    const book={};
    for(const key of FIELDS)if(['string','number'].includes(typeof value[key]))book[key]=String(value[key]).slice(0,key==='description'?50000:4000);
    book.authors=Array.isArray(value.authors)?value.authors.filter(v=>typeof v==='string').slice(0,30).map(v=>v.slice(0,400)):[];
    book.cover=safeUrl(value.cover,true);book.url=safeUrl(value.url);
    return book;
  }
  function publicData(kind,value) {
    if(kind==='details')return publicBook(value);
    if(!['featured','search'].includes(kind)||!value||!Array.isArray(value.books))return null;
    const data={books:value.books.slice(0,100).map(publicBook).filter(Boolean)};
    if(kind==='search'){
      data.page=Math.max(1,Number(value.page)||1);data.total_pages=Math.max(1,Number(value.total_pages)||1);
    }
    return data;
  }
  function mergeBookDetails(seed,details){
    const fields=Object.fromEntries(Object.entries(details).filter(([key,value])=>key==='description'||(value!==''&&value!=null&&(!Array.isArray(value)||value.length>0))));
    return publicBook({...seed,...fields});
  }
  function createBookCache(provider,options={}) {
    let disk=null,scope='default';
    try {disk=typeof provider==='function'?provider():provider;}catch{}
    const memory=new Map(),now=options.now||Date.now,maxEntries=options.maxEntries||80,maxBytes=options.maxBytes||2*1024*1024;
    const keyFor=(kind,key,context)=>PREFIX+JSON.stringify([context,kind,String(key)]);
    function pruneMemory(){
      let bytes=[...memory.values()].reduce((sum,row)=>sum+row.bytes,0);
      for(const [key,row] of memory){
        if(row.expiresAt<=now()||memory.size>maxEntries||bytes>maxBytes){memory.delete(key);bytes-=row.bytes;}
      }
    }
    function diskRows(){
      const rows=[];
      for(let i=0;i<disk.length;i++){
        const key=disk.key(i);if(!key?.startsWith(PREFIX))continue;
        try{const raw=disk.getItem(key);const row=JSON.parse(raw);rows.push({key,bytes:raw.length*2,savedAt:row.savedAt||0,expiresAt:row.expiresAt||0});}catch{rows.push({key,bytes:0,savedAt:0,expiresAt:0});}
      }
      return rows.sort((a,b)=>a.savedAt-b.savedAt);
    }
    function get(kind,key,context=scope){
      const name=keyFor(kind,key,context);
      try{
        const row=memory.get(name)||(disk?JSON.parse(disk.getItem(name)||'null'):null);
        if(!row||!Number.isFinite(row.expiresAt)||row.expiresAt<=now()){
          memory.delete(name);try{disk?.removeItem(name);}catch{}return null;
        }
        return publicData(kind,row.data);
      }catch{return null;}
    }
    function put(kind,key,value,ttl,context=scope){
      const data=publicData(kind,value);if(!data||!(ttl>0))return false;
      const name=keyFor(kind,key,context),row={savedAt:now(),expiresAt:now()+ttl,data};
      const raw=JSON.stringify(row);row.bytes=raw.length*2;if(row.bytes>maxBytes)return false;
      memory.delete(name);memory.set(name,row);pruneMemory();
      if(disk)try{
        // Evict our own oldest entries before writes; never remove theme or other app data.
        const rows=diskRows().filter(item=>item.key!==name);
        let bytes=rows.reduce((sum,item)=>sum+item.bytes,0)+row.bytes,count=rows.length+1;
        for(const item of rows){
          if(item.expiresAt<=now()||bytes>maxBytes||count>maxEntries){disk.removeItem(item.key);bytes-=item.bytes;count--;}
        }
        try{disk.setItem(name,raw);}catch{
          for(const item of rows){disk.removeItem(item.key);try{disk.setItem(name,raw);break;}catch{}}
        }
      }catch{}
      return true;
    }
    return Object.freeze({get,put,mergeDetails:mergeBookDetails,setScope:value=>{scope=String(value)},scope:()=>scope,
      searchKey:criteria=>JSON.stringify([String(criteria.query||'').trim(),criteria.format||'',criteria.language||'',Number(criteria.page)||1])});
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={createBookCache,mergeBookDetails};
  if(root)root.BookCache=createBookCache(()=>root.localStorage);
})(typeof window!=='undefined'?window:null);
