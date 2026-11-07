const test = require('node:test');
const assert = require('node:assert/strict');
const { createBookCache } = require('./static/book-cache.js');
const cacheModule = require('./static/book-cache.js');

function storage() {
  const values=new Map();
  return {get length(){return values.size}, key:i=>[...values.keys()][i]??null,
    getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)};
}
const book={id:'42:abc',name:'Book',authors:['Author'],description:'A synopsis',extension:'pdf',password:'secret',download_url:'signed-secret'};
test('metadata survives reload, excludes secrets, and expires',()=>{
  const disk=storage();let time=1000;
  const first=createBookCache(disk,{now:()=>time});first.setScope('library-a');
  first.put('details','42:abc',book,100);
  const reopened=createBookCache(disk,{now:()=>time});reopened.setScope('library-a');
  assert.equal(reopened.get('details','42:abc').description,'A synopsis');
  assert.equal(reopened.get('details','42:abc').password,undefined);
  assert.equal(reopened.get('details','42:abc').download_url,undefined);
  time=1101;assert.equal(reopened.get('details','42:abc'),null);
});
test('library scopes and search filters cannot share a result',()=>{
  const cache=createBookCache(storage());cache.setScope('a');cache.put('details',book.id,book,10000);
  cache.setScope('b');assert.equal(cache.get('details',book.id),null);
  const key=cache.searchKey({query:'text',format:'pdf',language:'chinese',page:1});
  assert.notEqual(key,cache.searchKey({query:'text',format:'epub',language:'chinese',page:1}));
  assert.notEqual(key,cache.searchKey({query:'text',format:'pdf',language:'chinese',page:2}));
});
test('blocked storage degrades to bounded memory without breaking reads',()=>{
  let time=1000;
  const cache=createBookCache(()=>{throw Error('blocked')},{now:()=>time,maxEntries:2});
  cache.put('details','1:a',{...book,id:'1:a'},10000);time++;
  cache.put('details','2:b',{...book,id:'2:b'},10000);time++;
  cache.put('details','3:c',{...book,id:'3:c'},10000);
  assert.equal(cache.get('details','1:a'),null);assert.equal(cache.get('details','3:c').id,'3:c');
});
test('disk eviction leaves other application preferences untouched',()=>{
  const disk=storage();disk.setItem('shiye-theme','dark');let time=1000;
  const cache=createBookCache(disk,{now:()=>time,maxEntries:2});
  for(const id of ['1:a','2:b','3:c']){cache.put('details',id,{...book,id},10000);time++;}
  const reopened=createBookCache(disk,{now:()=>time,maxEntries:2});
  assert.equal(reopened.get('details','1:a'),null);assert.ok(reopened.get('details','3:c'));
  assert.equal(disk.getItem('shiye-theme'),'dark');
});
test('sparse CLI details preserve cached search cover and source after a server restart',()=>{
  const seed={...book,cover:'https://s3proxy-alp2-covers.cdn-zlib.sk/covers/book.jpg',url:'https://library.example/book/42/abc'};
  const merged=cacheModule.mergeBookDetails(seed,{id:book.id,name:'Updated',cover:'',url:'',authors:[],description:''});
  assert.equal(merged.cover,seed.cover);assert.equal(merged.url,seed.url);assert.deepEqual(merged.authors,['Author']);
  assert.equal(merged.description,'');assert.equal(merged.name,'Updated');
});
test('temporary URL parameters are stripped from cached covers',()=>{
  const disk=storage(),cache=createBookCache(disk);
  cache.put('details',book.id,{...book,cover:'https://s3proxy-alp2-covers.cdn-zlib.sk/covers/book.jpg?token=signed-secret#fragment'},10000);
  assert.equal(cache.get('details',book.id).cover,'https://s3proxy-alp2-covers.cdn-zlib.sk/covers/book.jpg');
  for(let i=0;i<disk.length;i++)assert.equal(disk.getItem(disk.key(i)).includes('signed-secret'),false);
});
