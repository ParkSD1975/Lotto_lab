const url = 'https://dkcflmyoscudawleglzb.supabase.co/rest/v1/ai_custom_analyses?select=*&limit=1';
const key = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo';

async function checkSupabase() {
    try {
        console.log('Connecting to Supabase...');
        const response = await fetch(url, {
            headers: {
                'apikey': key,
                'Authorization': `Bearer ${key}`
            }
        });

        if (!response.ok) {
            // 404 might mean table doesn't exist, which is also a finding
            throw new Error(`HTTP Error: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        console.log('✅ Connection Successful!');
        console.log('Data retrieved from table "ai_custom_analyses":');
        console.log(JSON.stringify(data, null, 2));
    } catch (error) {
        console.error('❌ Connection Failed:', error.message);
    }
}

checkSupabase();
