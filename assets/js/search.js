const search = new Vue({
    el: '#search',
    data: {
	docs: null,
	idx: null,
	term: '',
	results: null
    },
    async created() {
	let result = await fetch('/search_data.json');
	docs = await result.json();
	this.idx = lunr(function () {
	    this.ref('id');
	    this.field('t');
	    this.field('log');
	    docs.forEach(function (doc, idx) {
		doc.id = idx;
		this.add(doc);
	    }, this);
	});
	this.docs = docs;
    },
    computed: {
	noResults() {
	    return this.results.length === 0;
	}
    },
    methods:{
	search() {
	    console.log('search', this.term);
	    let results = this.idx.search(this.term);

	    // we need to add title, url from ref
	    results.forEach(r => {
		r.title = this.docs[r.ref].title;
		r.url = this.docs[r.ref].url;
	    });

	    this.results = results;
	}
    }
});
