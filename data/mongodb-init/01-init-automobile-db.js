// ============================================================================
// AUTOMOBILE SECTOR MONGODB INITIALIZATION SCRIPT
// Comprehensive mock data with realistic values
// ============================================================================

// Switch to the automobile database
db = db.getSiblingDB('automobile_db');

// Create a user for the automobile database
db.createUser({
    user: 'automobile_user',
    pwd: 'automobile_pass',
    roles: [
        { role: 'readWrite', db: 'automobile_db' },
        { role: 'dbAdmin', db: 'automobile_db' }
    ]
});

print('Starting automobile data initialization...');

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function randomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomFloat(min, max, decimals = 2) {
    return parseFloat((Math.random() * (max - min) + min).toFixed(decimals));
}

function randomElement(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
}

function randomDate(startYear, endYear) {
    const start = new Date(startYear, 0, 1);
    const end = new Date(endYear, 11, 31);
    return new Date(start.getTime() + Math.random() * (end.getTime() - start.getTime()));
}

function generateVIN() {
    const chars = 'ABCDEFGHJKLMNPRSTUVWXYZ0123456789';
    let vin = '';
    for (let i = 0; i < 17; i++) {
        vin += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return vin;
}

function generatePhone() {
    return `(${randomInt(200, 999)}) ${randomInt(200, 999)}-${randomInt(1000, 9999)}`;
}

function generateEmail(firstName, lastName, domain) {
    return `${firstName.toLowerCase()}.${lastName.toLowerCase()}@${domain}`;
}

// ============================================================================
// 1. MANUFACTURERS / BRANDS
// ============================================================================

const manufacturers = [
    {
        manufacturer_id: 'MFR001',
        name: 'Toyota',
        country: 'Japan',
        founded_year: 1937,
        headquarters: 'Toyota City, Aichi, Japan',
        ceo: 'Koji Sato',
        employees: 375000,
        annual_revenue_billions: 275.4,
        website: 'https://www.toyota.com',
        stock_symbol: 'TM',
        brands: ['Toyota', 'Lexus'],
        specializations: ['Hybrid Technology', 'Reliability', 'Mass Market'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR002',
        name: 'Ford Motor Company',
        country: 'United States',
        founded_year: 1903,
        headquarters: 'Dearborn, Michigan, USA',
        ceo: 'Jim Farley',
        employees: 173000,
        annual_revenue_billions: 158.1,
        website: 'https://www.ford.com',
        stock_symbol: 'F',
        brands: ['Ford', 'Lincoln'],
        specializations: ['Trucks', 'Electric Vehicles', 'American Heritage'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR003',
        name: 'General Motors',
        country: 'United States',
        founded_year: 1908,
        headquarters: 'Detroit, Michigan, USA',
        ceo: 'Mary Barra',
        employees: 167000,
        annual_revenue_billions: 156.7,
        website: 'https://www.gm.com',
        stock_symbol: 'GM',
        brands: ['Chevrolet', 'GMC', 'Cadillac', 'Buick'],
        specializations: ['Full Range', 'Electric Vehicles', 'Trucks'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR004',
        name: 'Honda Motor Company',
        country: 'Japan',
        founded_year: 1948,
        headquarters: 'Minato, Tokyo, Japan',
        ceo: 'Toshihiro Mibe',
        employees: 204000,
        annual_revenue_billions: 129.2,
        website: 'https://www.honda.com',
        stock_symbol: 'HMC',
        brands: ['Honda', 'Acura'],
        specializations: ['Engines', 'Reliability', 'Motorcycles'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR005',
        name: 'Volkswagen Group',
        country: 'Germany',
        founded_year: 1937,
        headquarters: 'Wolfsburg, Germany',
        ceo: 'Oliver Blume',
        employees: 675000,
        annual_revenue_billions: 295.8,
        website: 'https://www.volkswagen.com',
        stock_symbol: 'VWAGY',
        brands: ['Volkswagen', 'Audi', 'Porsche', 'Bentley', 'Lamborghini'],
        specializations: ['German Engineering', 'Luxury', 'Performance'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR006',
        name: 'BMW Group',
        country: 'Germany',
        founded_year: 1916,
        headquarters: 'Munich, Germany',
        ceo: 'Oliver Zipse',
        employees: 149000,
        annual_revenue_billions: 142.6,
        website: 'https://www.bmw.com',
        stock_symbol: 'BMWYY',
        brands: ['BMW', 'MINI', 'Rolls-Royce'],
        specializations: ['Luxury', 'Performance', 'Electric'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR007',
        name: 'Mercedes-Benz Group',
        country: 'Germany',
        founded_year: 1926,
        headquarters: 'Stuttgart, Germany',
        ceo: 'Ola Kallenius',
        employees: 172000,
        annual_revenue_billions: 150.0,
        website: 'https://www.mercedes-benz.com',
        stock_symbol: 'MBGYY',
        brands: ['Mercedes-Benz', 'Mercedes-AMG', 'Mercedes-Maybach'],
        specializations: ['Luxury', 'Innovation', 'Safety'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR008',
        name: 'Tesla Inc',
        country: 'United States',
        founded_year: 2003,
        headquarters: 'Austin, Texas, USA',
        ceo: 'Elon Musk',
        employees: 140000,
        annual_revenue_billions: 96.8,
        website: 'https://www.tesla.com',
        stock_symbol: 'TSLA',
        brands: ['Tesla'],
        specializations: ['Electric Vehicles', 'Autonomous Driving', 'Energy Storage'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR009',
        name: 'Hyundai Motor Group',
        country: 'South Korea',
        founded_year: 1967,
        headquarters: 'Seoul, South Korea',
        ceo: 'Jaehoon Chang',
        employees: 280000,
        annual_revenue_billions: 117.0,
        website: 'https://www.hyundai.com',
        stock_symbol: 'HYMTF',
        brands: ['Hyundai', 'Kia', 'Genesis'],
        specializations: ['Value', 'Design', 'Electric Vehicles'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR010',
        name: 'Nissan Motor Corporation',
        country: 'Japan',
        founded_year: 1933,
        headquarters: 'Yokohama, Japan',
        ceo: 'Makoto Uchida',
        employees: 134000,
        annual_revenue_billions: 75.6,
        website: 'https://www.nissan.com',
        stock_symbol: 'NSANY',
        brands: ['Nissan', 'Infiniti'],
        specializations: ['Electric Vehicles', 'Crossovers', 'Technology'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR011',
        name: 'Stellantis',
        country: 'Netherlands',
        founded_year: 2021,
        headquarters: 'Amsterdam, Netherlands',
        ceo: 'Carlos Tavares',
        employees: 281000,
        annual_revenue_billions: 189.5,
        website: 'https://www.stellantis.com',
        stock_symbol: 'STLA',
        brands: ['Jeep', 'Ram', 'Dodge', 'Chrysler', 'Alfa Romeo', 'Maserati', 'Fiat', 'Peugeot'],
        specializations: ['Diverse Portfolio', 'SUVs', 'Trucks'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR012',
        name: 'Subaru Corporation',
        country: 'Japan',
        founded_year: 1953,
        headquarters: 'Shibuya, Tokyo, Japan',
        ceo: 'Atsushi Osaki',
        employees: 37000,
        annual_revenue_billions: 28.3,
        website: 'https://www.subaru.com',
        stock_symbol: 'FUJHY',
        brands: ['Subaru'],
        specializations: ['All-Wheel Drive', 'Safety', 'Outdoor Lifestyle'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR013',
        name: 'Mazda Motor Corporation',
        country: 'Japan',
        founded_year: 1920,
        headquarters: 'Fuchu, Hiroshima, Japan',
        ceo: 'Masahiro Moro',
        employees: 48000,
        annual_revenue_billions: 30.5,
        website: 'https://www.mazda.com',
        stock_symbol: 'MZDAY',
        brands: ['Mazda'],
        specializations: ['Driving Dynamics', 'Design', 'SkyActiv Technology'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR014',
        name: 'Rivian Automotive',
        country: 'United States',
        founded_year: 2009,
        headquarters: 'Irvine, California, USA',
        ceo: 'RJ Scaringe',
        employees: 16000,
        annual_revenue_billions: 4.4,
        website: 'https://www.rivian.com',
        stock_symbol: 'RIVN',
        brands: ['Rivian'],
        specializations: ['Electric Trucks', 'Adventure Vehicles', 'Sustainability'],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        manufacturer_id: 'MFR015',
        name: 'Lucid Motors',
        country: 'United States',
        founded_year: 2007,
        headquarters: 'Newark, California, USA',
        ceo: 'Peter Rawlinson',
        employees: 7000,
        annual_revenue_billions: 0.8,
        website: 'https://www.lucidmotors.com',
        stock_symbol: 'LCID',
        brands: ['Lucid'],
        specializations: ['Luxury Electric', 'Range', 'Performance'],
        created_at: new Date(),
        updated_at: new Date()
    }
];

db.manufacturers.insertMany(manufacturers);
print(`Inserted ${manufacturers.length} manufacturers`);

// ============================================================================
// 2. VEHICLE MODELS (Comprehensive catalog)
// ============================================================================

const vehicleModels = [
    // Toyota Models
    { model_id: 'MOD001', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'Camry', body_type: 'Sedan', segment: 'Mid-size', base_msrp: 26420, year_introduced: 1982, current_generation: 9, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.5L I4', '2.5L I4 Hybrid'], horsepower_range: { min: 203, max: 225 }, mpg_city: 28, mpg_highway: 39, seating_capacity: 5, cargo_volume_cf: 15.1, safety_rating: 5, features: ['Toyota Safety Sense', 'Apple CarPlay', 'Android Auto', 'Wireless Charging'] },
    { model_id: 'MOD002', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'Corolla', body_type: 'Sedan', segment: 'Compact', base_msrp: 22050, year_introduced: 1966, current_generation: 12, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD'], engine_options: ['1.8L I4', '2.0L I4', '1.8L I4 Hybrid'], horsepower_range: { min: 139, max: 196 }, mpg_city: 31, mpg_highway: 40, seating_capacity: 5, cargo_volume_cf: 13.1, safety_rating: 5, features: ['Toyota Safety Sense', 'LED Headlights', 'Multi-Information Display'] },
    { model_id: 'MOD003', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'RAV4', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 28475, year_introduced: 1994, current_generation: 5, fuel_types: ['Gasoline', 'Hybrid', 'Plug-in Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.5L I4', '2.5L I4 Hybrid', '2.5L PHEV'], horsepower_range: { min: 203, max: 302 }, mpg_city: 27, mpg_highway: 35, seating_capacity: 5, cargo_volume_cf: 37.6, safety_rating: 5, features: ['Toyota Safety Sense', 'AWD Lock', 'Multi-Terrain Select'] },
    { model_id: 'MOD004', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'Highlander', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 39070, year_introduced: 2000, current_generation: 4, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.4L Turbo I4', '2.5L I4 Hybrid'], horsepower_range: { min: 265, max: 362 }, mpg_city: 22, mpg_highway: 29, seating_capacity: 8, cargo_volume_cf: 16.0, safety_rating: 5, features: ['Premium Audio', 'Panoramic Moonroof', 'Heated Seats'] },
    { model_id: 'MOD005', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'Tacoma', body_type: 'Truck', segment: 'Mid-size Truck', base_msrp: 31500, year_introduced: 1995, current_generation: 4, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['RWD', '4WD'], engine_options: ['2.4L Turbo I4', '2.4L I4 Hybrid'], horsepower_range: { min: 228, max: 326 }, mpg_city: 19, mpg_highway: 24, seating_capacity: 5, cargo_volume_cf: null, safety_rating: 5, features: ['TRD Off-Road Package', 'Crawl Control', 'Multi-Terrain Select'] },
    { model_id: 'MOD006', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'Tundra', body_type: 'Truck', segment: 'Full-size Truck', base_msrp: 39965, year_introduced: 1999, current_generation: 3, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['RWD', '4WD'], engine_options: ['3.4L Twin-Turbo V6', '3.4L Twin-Turbo V6 Hybrid'], horsepower_range: { min: 348, max: 437 }, mpg_city: 18, mpg_highway: 24, seating_capacity: 6, cargo_volume_cf: null, safety_rating: 5, features: ['i-FORCE MAX Hybrid', 'Tow Technology Package', 'Panoramic View Monitor'] },
    { model_id: 'MOD007', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: 'Prius', body_type: 'Hatchback', segment: 'Compact', base_msrp: 29350, year_introduced: 1997, current_generation: 5, fuel_types: ['Hybrid', 'Plug-in Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.0L I4 Hybrid', '2.0L PHEV'], horsepower_range: { min: 194, max: 220 }, mpg_city: 57, mpg_highway: 56, seating_capacity: 5, cargo_volume_cf: 20.3, safety_rating: 5, features: ['Solar Roof', 'Digital Key', 'Bi-Tone Roof'] },
    { model_id: 'MOD008', manufacturer_id: 'MFR001', brand: 'Toyota', model_name: '4Runner', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 40770, year_introduced: 1984, current_generation: 6, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['RWD', '4WD'], engine_options: ['2.4L Turbo I4', '2.4L I4 Hybrid'], horsepower_range: { min: 278, max: 326 }, mpg_city: 17, mpg_highway: 22, seating_capacity: 5, cargo_volume_cf: 44.0, safety_rating: 5, features: ['Crawl Control', 'Multi-Terrain Select', 'Locking Rear Differential'] },
    { model_id: 'MOD009', manufacturer_id: 'MFR001', brand: 'Lexus', model_name: 'ES', body_type: 'Sedan', segment: 'Luxury Mid-size', base_msrp: 42490, year_introduced: 1989, current_generation: 7, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD'], engine_options: ['2.5L I4', '2.5L I4 Hybrid'], horsepower_range: { min: 203, max: 302 }, mpg_city: 25, mpg_highway: 34, seating_capacity: 5, cargo_volume_cf: 13.9, safety_rating: 5, features: ['Mark Levinson Audio', 'Lexus Safety System+', 'Bamboo Trim'] },
    { model_id: 'MOD010', manufacturer_id: 'MFR001', brand: 'Lexus', model_name: 'RX', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 49150, year_introduced: 1998, current_generation: 5, fuel_types: ['Gasoline', 'Hybrid', 'Plug-in Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.4L Turbo I4', '2.5L I4 Hybrid', '2.5L PHEV'], horsepower_range: { min: 275, max: 366 }, mpg_city: 21, mpg_highway: 28, seating_capacity: 5, cargo_volume_cf: 29.6, safety_rating: 5, features: ['14-inch Touchscreen', 'Panoramic Moonroof', 'Mark Levinson Audio'] },

    // Ford Models
    { model_id: 'MOD011', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'F-150', body_type: 'Truck', segment: 'Full-size Truck', base_msrp: 36495, year_introduced: 1948, current_generation: 14, fuel_types: ['Gasoline', 'Hybrid', 'Electric'], drivetrain_options: ['RWD', '4WD'], engine_options: ['3.3L V6', '2.7L EcoBoost V6', '3.5L EcoBoost V6', '5.0L V8', '3.5L PowerBoost Hybrid'], horsepower_range: { min: 290, max: 563 }, mpg_city: 20, mpg_highway: 26, seating_capacity: 6, cargo_volume_cf: null, safety_rating: 5, features: ['Pro Power Onboard', 'BlueCruise', 'Tailgate Work Surface'] },
    { model_id: 'MOD012', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'F-150 Lightning', body_type: 'Truck', segment: 'Electric Full-size Truck', base_msrp: 55995, year_introduced: 2022, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor Electric'], horsepower_range: { min: 452, max: 580 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 14.1, safety_rating: 5, features: ['Pro Power Onboard', 'Intelligent Backup Power', 'Mega Power Frunk'], ev_range_miles: 320, battery_kwh: 131 },
    { model_id: 'MOD013', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'Mustang', body_type: 'Coupe', segment: 'Sports Car', base_msrp: 32515, year_introduced: 1964, current_generation: 7, fuel_types: ['Gasoline'], drivetrain_options: ['RWD'], engine_options: ['2.3L EcoBoost I4', '5.0L Coyote V8'], horsepower_range: { min: 315, max: 500 }, mpg_city: 18, mpg_highway: 27, seating_capacity: 4, cargo_volume_cf: 13.5, safety_rating: 4, features: ['Active Exhaust', 'MagneRide Damping', 'Digital Cluster'] },
    { model_id: 'MOD014', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'Mustang Mach-E', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 42995, year_introduced: 2020, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 266, max: 480 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 29.7, safety_rating: 5, features: ['BlueCruise', '15.5-inch Touchscreen', 'Phone As A Key'], ev_range_miles: 312, battery_kwh: 91 },
    { model_id: 'MOD015', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'Bronco', body_type: 'SUV', segment: 'Mid-size Off-Road SUV', base_msrp: 38745, year_introduced: 1966, current_generation: 6, fuel_types: ['Gasoline'], drivetrain_options: ['4WD'], engine_options: ['2.3L EcoBoost I4', '2.7L EcoBoost V6'], horsepower_range: { min: 300, max: 330 }, mpg_city: 18, mpg_highway: 22, seating_capacity: 5, cargo_volume_cf: 35.6, safety_rating: 4, features: ['Removable Roof', 'Trail Turn Assist', 'G.O.A.T. Modes'] },
    { model_id: 'MOD016', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'Explorer', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 38355, year_introduced: 1990, current_generation: 6, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['2.3L EcoBoost I4', '3.0L EcoBoost V6', '3.3L Hybrid V6'], horsepower_range: { min: 300, max: 500 }, mpg_city: 21, mpg_highway: 28, seating_capacity: 7, cargo_volume_cf: 18.2, safety_rating: 5, features: ['BlueCruise', 'Terrain Management System', '360-Degree Camera'] },
    { model_id: 'MOD017', manufacturer_id: 'MFR002', brand: 'Ford', model_name: 'Escape', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 29615, year_introduced: 2000, current_generation: 4, fuel_types: ['Gasoline', 'Hybrid', 'Plug-in Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['1.5L EcoBoost I3', '2.0L EcoBoost I4', '2.5L Hybrid I4', '2.5L PHEV I4'], horsepower_range: { min: 180, max: 221 }, mpg_city: 28, mpg_highway: 34, seating_capacity: 5, cargo_volume_cf: 33.5, safety_rating: 5, features: ['Ford Co-Pilot360', 'Slide-and-Recline Rear Seats', 'Hands-Free Liftgate'] },
    { model_id: 'MOD018', manufacturer_id: 'MFR002', brand: 'Lincoln', model_name: 'Navigator', body_type: 'SUV', segment: 'Full-size Luxury SUV', base_msrp: 81000, year_introduced: 1998, current_generation: 4, fuel_types: ['Gasoline'], drivetrain_options: ['RWD', '4WD'], engine_options: ['3.5L Twin-Turbo V6'], horsepower_range: { min: 440, max: 440 }, mpg_city: 16, mpg_highway: 22, seating_capacity: 8, cargo_volume_cf: 19.3, safety_rating: 5, features: ['30-Way Adjustable Seats', 'Revel Audio', 'Lincoln Embrace'] },

    // General Motors Models
    { model_id: 'MOD019', manufacturer_id: 'MFR003', brand: 'Chevrolet', model_name: 'Silverado 1500', body_type: 'Truck', segment: 'Full-size Truck', base_msrp: 37645, year_introduced: 1999, current_generation: 4, fuel_types: ['Gasoline', 'Diesel'], drivetrain_options: ['RWD', '4WD'], engine_options: ['2.7L Turbo I4', '5.3L V8', '6.2L V8', '3.0L Duramax Diesel'], horsepower_range: { min: 310, max: 420 }, mpg_city: 16, mpg_highway: 24, seating_capacity: 6, cargo_volume_cf: null, safety_rating: 5, features: ['Super Cruise', 'Multi-Flex Tailgate', 'Advanced Trailering System'] },
    { model_id: 'MOD020', manufacturer_id: 'MFR003', brand: 'Chevrolet', model_name: 'Equinox', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 30500, year_introduced: 2004, current_generation: 3, fuel_types: ['Gasoline', 'Electric'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['1.5L Turbo I4'], horsepower_range: { min: 175, max: 175 }, mpg_city: 26, mpg_highway: 31, seating_capacity: 5, cargo_volume_cf: 29.9, safety_rating: 5, features: ['Chevy Safety Assist', 'Wireless Apple CarPlay', '17-inch Wheels'] },
    { model_id: 'MOD021', manufacturer_id: 'MFR003', brand: 'Chevrolet', model_name: 'Equinox EV', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 34995, year_introduced: 2024, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 210, max: 300 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 57.0, safety_rating: 5, features: ['Super Cruise', 'One-Pedal Driving', '17.7-inch Display'], ev_range_miles: 319, battery_kwh: 85 },
    { model_id: 'MOD022', manufacturer_id: 'MFR003', brand: 'Chevrolet', model_name: 'Tahoe', body_type: 'SUV', segment: 'Full-size SUV', base_msrp: 58795, year_introduced: 1995, current_generation: 5, fuel_types: ['Gasoline', 'Diesel'], drivetrain_options: ['RWD', '4WD'], engine_options: ['5.3L V8', '6.2L V8', '3.0L Duramax Diesel'], horsepower_range: { min: 277, max: 420 }, mpg_city: 14, mpg_highway: 20, seating_capacity: 9, cargo_volume_cf: 25.5, safety_rating: 5, features: ['Magnetic Ride Control', 'Air Ride Adaptive Suspension', 'Super Cruise'] },
    { model_id: 'MOD023', manufacturer_id: 'MFR003', brand: 'Chevrolet', model_name: 'Corvette', body_type: 'Coupe', segment: 'Sports Car', base_msrp: 66300, year_introduced: 1953, current_generation: 8, fuel_types: ['Gasoline', 'Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['6.2L V8', '5.5L Flat-Plane V8', 'E-Ray Hybrid'], horsepower_range: { min: 490, max: 655 }, mpg_city: 15, mpg_highway: 24, seating_capacity: 2, cargo_volume_cf: 12.6, safety_rating: null, features: ['Magnetic Ride Control', 'Z51 Performance Package', 'Removable Roof Panel'] },
    { model_id: 'MOD024', manufacturer_id: 'MFR003', brand: 'GMC', model_name: 'Sierra 1500', body_type: 'Truck', segment: 'Full-size Truck', base_msrp: 40500, year_introduced: 1999, current_generation: 4, fuel_types: ['Gasoline', 'Diesel'], drivetrain_options: ['RWD', '4WD'], engine_options: ['2.7L Turbo I4', '5.3L V8', '6.2L V8', '3.0L Duramax Diesel'], horsepower_range: { min: 310, max: 420 }, mpg_city: 16, mpg_highway: 24, seating_capacity: 6, cargo_volume_cf: null, safety_rating: 5, features: ['Super Cruise', 'MultiPro Tailgate', 'CarbonPro Bed'] },
    { model_id: 'MOD025', manufacturer_id: 'MFR003', brand: 'GMC', model_name: 'Yukon', body_type: 'SUV', segment: 'Full-size SUV', base_msrp: 62100, year_introduced: 1992, current_generation: 5, fuel_types: ['Gasoline', 'Diesel'], drivetrain_options: ['RWD', '4WD'], engine_options: ['5.3L V8', '6.2L V8', '3.0L Duramax Diesel'], horsepower_range: { min: 277, max: 420 }, mpg_city: 14, mpg_highway: 20, seating_capacity: 9, cargo_volume_cf: 25.5, safety_rating: 5, features: ['Magnetic Ride Control', 'Super Cruise', 'Rear Pedestrian Alert'] },
    { model_id: 'MOD026', manufacturer_id: 'MFR003', brand: 'GMC', model_name: 'Hummer EV', body_type: 'Truck', segment: 'Electric Full-size Truck', base_msrp: 98845, year_introduced: 2022, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Tri-Motor Electric'], horsepower_range: { min: 625, max: 1000 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 11.0, safety_rating: null, features: ['CrabWalk', 'Extract Mode', 'Super Cruise'], ev_range_miles: 329, battery_kwh: 212.7 },
    { model_id: 'MOD027', manufacturer_id: 'MFR003', brand: 'Cadillac', model_name: 'Escalade', body_type: 'SUV', segment: 'Full-size Luxury SUV', base_msrp: 81890, year_introduced: 1999, current_generation: 5, fuel_types: ['Gasoline', 'Diesel', 'Electric'], drivetrain_options: ['RWD', '4WD'], engine_options: ['6.2L V8', '3.0L Duramax Diesel'], horsepower_range: { min: 277, max: 420 }, mpg_city: 14, mpg_highway: 19, seating_capacity: 8, cargo_volume_cf: 25.5, safety_rating: 5, features: ['Super Cruise', 'AKG Studio Audio', '38-inch Curved OLED Display'] },
    { model_id: 'MOD028', manufacturer_id: 'MFR003', brand: 'Cadillac', model_name: 'Lyriq', body_type: 'SUV', segment: 'Electric Luxury SUV', base_msrp: 58590, year_introduced: 2023, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 340, max: 500 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 28.0, safety_rating: 5, features: ['Super Cruise', '33-inch LED Display', 'AKG Audio'], ev_range_miles: 314, battery_kwh: 102 },

    // Honda Models
    { model_id: 'MOD029', manufacturer_id: 'MFR004', brand: 'Honda', model_name: 'Accord', body_type: 'Sedan', segment: 'Mid-size', base_msrp: 28990, year_introduced: 1976, current_generation: 11, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD'], engine_options: ['1.5L Turbo I4', '2.0L I4 Hybrid'], horsepower_range: { min: 192, max: 204 }, mpg_city: 29, mpg_highway: 37, seating_capacity: 5, cargo_volume_cf: 16.7, safety_rating: 5, features: ['Honda Sensing', 'Google Built-In', 'Wireless CarPlay'] },
    { model_id: 'MOD030', manufacturer_id: 'MFR004', brand: 'Honda', model_name: 'Civic', body_type: 'Sedan', segment: 'Compact', base_msrp: 24950, year_introduced: 1972, current_generation: 11, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD'], engine_options: ['2.0L I4', '1.5L Turbo I4', '2.0L I4 Hybrid'], horsepower_range: { min: 150, max: 200 }, mpg_city: 31, mpg_highway: 40, seating_capacity: 5, cargo_volume_cf: 14.8, safety_rating: 5, features: ['Honda Sensing', 'Bose Audio', 'Wireless Charging'] },
    { model_id: 'MOD031', manufacturer_id: 'MFR004', brand: 'Honda', model_name: 'CR-V', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 30050, year_introduced: 1995, current_generation: 6, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['1.5L Turbo I4', '2.0L I4 Hybrid'], horsepower_range: { min: 190, max: 204 }, mpg_city: 28, mpg_highway: 34, seating_capacity: 5, cargo_volume_cf: 36.3, safety_rating: 5, features: ['Honda Sensing', 'Hands-Free Access Power Tailgate', 'Wireless Charging'] },
    { model_id: 'MOD032', manufacturer_id: 'MFR004', brand: 'Honda', model_name: 'Pilot', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 40100, year_introduced: 2002, current_generation: 4, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['3.5L V6'], horsepower_range: { min: 285, max: 285 }, mpg_city: 19, mpg_highway: 27, seating_capacity: 8, cargo_volume_cf: 18.6, safety_rating: 5, features: ['Honda Sensing', 'TrailSport Package', 'Rear Entertainment System'] },
    { model_id: 'MOD033', manufacturer_id: 'MFR004', brand: 'Honda', model_name: 'Prologue', body_type: 'SUV', segment: 'Electric Mid-size SUV', base_msrp: 47400, year_introduced: 2024, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 212, max: 288 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 26.9, safety_rating: 5, features: ['Honda Sensing 360', 'Google Built-In', '11.3-inch Display'], ev_range_miles: 296, battery_kwh: 85 },
    { model_id: 'MOD034', manufacturer_id: 'MFR004', brand: 'Acura', model_name: 'MDX', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 50200, year_introduced: 2000, current_generation: 4, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'SH-AWD'], engine_options: ['3.5L V6', '3.0L Turbo V6'], horsepower_range: { min: 290, max: 355 }, mpg_city: 19, mpg_highway: 26, seating_capacity: 7, cargo_volume_cf: 18.1, safety_rating: 5, features: ['AcuraWatch', 'ELS Studio Audio', 'True Touchpad Interface'] },

    // Tesla Models
    { model_id: 'MOD035', manufacturer_id: 'MFR008', brand: 'Tesla', model_name: 'Model 3', body_type: 'Sedan', segment: 'Electric Compact', base_msrp: 38990, year_introduced: 2017, current_generation: 2, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 283, max: 510 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 23.0, safety_rating: 5, features: ['Autopilot', 'Full Self-Driving Capability', '15-inch Touchscreen'], ev_range_miles: 363, battery_kwh: 82 },
    { model_id: 'MOD036', manufacturer_id: 'MFR008', brand: 'Tesla', model_name: 'Model Y', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 44990, year_introduced: 2020, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 283, max: 510 }, mpg_city: null, mpg_highway: null, seating_capacity: 7, cargo_volume_cf: 76.0, safety_rating: 5, features: ['Autopilot', 'Full Self-Driving Capability', 'Panoramic Glass Roof'], ev_range_miles: 330, battery_kwh: 82 },
    { model_id: 'MOD037', manufacturer_id: 'MFR008', brand: 'Tesla', model_name: 'Model S', body_type: 'Sedan', segment: 'Electric Luxury', base_msrp: 74990, year_introduced: 2012, current_generation: 2, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor', 'Tri Motor Plaid'], horsepower_range: { min: 670, max: 1020 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 28.0, safety_rating: 5, features: ['Autopilot', 'Yoke Steering', '17-inch Touchscreen'], ev_range_miles: 405, battery_kwh: 100 },
    { model_id: 'MOD038', manufacturer_id: 'MFR008', brand: 'Tesla', model_name: 'Model X', body_type: 'SUV', segment: 'Electric Luxury SUV', base_msrp: 79990, year_introduced: 2015, current_generation: 2, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor', 'Tri Motor Plaid'], horsepower_range: { min: 670, max: 1020 }, mpg_city: null, mpg_highway: null, seating_capacity: 7, cargo_volume_cf: 91.0, safety_rating: 5, features: ['Falcon Wing Doors', 'Autopilot', '17-inch Touchscreen'], ev_range_miles: 348, battery_kwh: 100 },
    { model_id: 'MOD039', manufacturer_id: 'MFR008', brand: 'Tesla', model_name: 'Cybertruck', body_type: 'Truck', segment: 'Electric Full-size Truck', base_msrp: 79990, year_introduced: 2023, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor', 'Tri Motor'], horsepower_range: { min: 315, max: 845 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 68.0, safety_rating: null, features: ['Stainless Steel Exoskeleton', 'Armored Glass', 'Vault Cover'], ev_range_miles: 340, battery_kwh: 123 },

    // Hyundai/Kia/Genesis Models
    { model_id: 'MOD040', manufacturer_id: 'MFR009', brand: 'Hyundai', model_name: 'Tucson', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 29250, year_introduced: 2004, current_generation: 4, fuel_types: ['Gasoline', 'Hybrid', 'Plug-in Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.5L I4', '1.6L Turbo Hybrid', '1.6L Turbo PHEV'], horsepower_range: { min: 187, max: 261 }, mpg_city: 26, mpg_highway: 33, seating_capacity: 5, cargo_volume_cf: 38.7, safety_rating: 5, features: ['Hyundai SmartSense', 'Digital Key', 'Bluelink'] },
    { model_id: 'MOD041', manufacturer_id: 'MFR009', brand: 'Hyundai', model_name: 'Palisade', body_type: 'SUV', segment: 'Full-size SUV', base_msrp: 37350, year_introduced: 2018, current_generation: 1, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['3.8L V6', '1.6L Turbo Hybrid'], horsepower_range: { min: 291, max: 291 }, mpg_city: 19, mpg_highway: 27, seating_capacity: 8, cargo_volume_cf: 18.0, safety_rating: 5, features: ['Hyundai SmartSense', 'Quilted Nappa Leather', 'Intercom'] },
    { model_id: 'MOD042', manufacturer_id: 'MFR009', brand: 'Hyundai', model_name: 'Ioniq 5', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 43300, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 225, max: 320 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 27.2, safety_rating: 5, features: ['800V Architecture', 'Vehicle-to-Load', 'Sliding Center Console'], ev_range_miles: 303, battery_kwh: 77.4 },
    { model_id: 'MOD043', manufacturer_id: 'MFR009', brand: 'Hyundai', model_name: 'Ioniq 6', body_type: 'Sedan', segment: 'Electric Mid-size', base_msrp: 45500, year_introduced: 2023, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 225, max: 320 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 12.1, safety_rating: 5, features: ['800V Architecture', '0.21 Drag Coefficient', 'Ambient Lighting'], ev_range_miles: 361, battery_kwh: 77.4 },
    { model_id: 'MOD044', manufacturer_id: 'MFR009', brand: 'Kia', model_name: 'Telluride', body_type: 'SUV', segment: 'Full-size SUV', base_msrp: 37690, year_introduced: 2019, current_generation: 1, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['3.8L V6'], horsepower_range: { min: 291, max: 291 }, mpg_city: 20, mpg_highway: 26, seating_capacity: 8, cargo_volume_cf: 21.0, safety_rating: 5, features: ['Highway Driving Assist', 'Blind-Spot View Monitor', 'Harman Kardon Audio'] },
    { model_id: 'MOD045', manufacturer_id: 'MFR009', brand: 'Kia', model_name: 'EV6', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 42600, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 225, max: 576 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 24.4, safety_rating: 5, features: ['800V Architecture', 'GT Mode', 'Vehicle-to-Load'], ev_range_miles: 310, battery_kwh: 77.4 },
    { model_id: 'MOD046', manufacturer_id: 'MFR009', brand: 'Genesis', model_name: 'GV80', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 59050, year_introduced: 2020, current_generation: 1, fuel_types: ['Gasoline'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['2.5L Turbo I4', '3.5L Twin-Turbo V6'], horsepower_range: { min: 300, max: 375 }, mpg_city: 18, mpg_highway: 23, seating_capacity: 7, cargo_volume_cf: 11.6, safety_rating: 5, features: ['Remote Smart Parking', 'Lexicon Audio', 'Ergo Motion Seats'] },

    // BMW Models
    { model_id: 'MOD047', manufacturer_id: 'MFR006', brand: 'BMW', model_name: '3 Series', body_type: 'Sedan', segment: 'Compact Luxury', base_msrp: 44450, year_introduced: 1975, current_generation: 7, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['2.0L Turbo I4', '3.0L Turbo I6', '2.0L PHEV'], horsepower_range: { min: 255, max: 382 }, mpg_city: 26, mpg_highway: 36, seating_capacity: 5, cargo_volume_cf: 13.0, safety_rating: 5, features: ['iDrive 8', 'M Sport Package', 'Adaptive LED Headlights'] },
    { model_id: 'MOD048', manufacturer_id: 'MFR006', brand: 'BMW', model_name: '5 Series', body_type: 'Sedan', segment: 'Mid-size Luxury', base_msrp: 57400, year_introduced: 1972, current_generation: 8, fuel_types: ['Gasoline', 'Plug-in Hybrid', 'Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['2.0L Turbo I4', '3.0L Turbo I6', 'Electric'], horsepower_range: { min: 255, max: 593 }, mpg_city: 25, mpg_highway: 34, seating_capacity: 5, cargo_volume_cf: 15.0, safety_rating: 5, features: ['Curved Display', 'Highway Assistant', 'Bowers & Wilkins Audio'] },
    { model_id: 'MOD049', manufacturer_id: 'MFR006', brand: 'BMW', model_name: 'X5', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 65200, year_introduced: 1999, current_generation: 4, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['3.0L Turbo I6', '4.4L Twin-Turbo V8', '3.0L PHEV'], horsepower_range: { min: 335, max: 617 }, mpg_city: 18, mpg_highway: 25, seating_capacity: 7, cargo_volume_cf: 33.9, safety_rating: 5, features: ['xOffroad Package', 'Air Suspension', 'Panoramic Sky Lounge'] },
    { model_id: 'MOD050', manufacturer_id: 'MFR006', brand: 'BMW', model_name: 'iX', body_type: 'SUV', segment: 'Electric Luxury SUV', base_msrp: 87100, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor'], horsepower_range: { min: 322, max: 610 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 35.5, safety_rating: 5, features: ['Shy Tech', 'Electrochromic Roof', 'Bowers & Wilkins'], ev_range_miles: 324, battery_kwh: 111.5 },

    // Mercedes-Benz Models
    { model_id: 'MOD051', manufacturer_id: 'MFR007', brand: 'Mercedes-Benz', model_name: 'C-Class', body_type: 'Sedan', segment: 'Compact Luxury', base_msrp: 46950, year_introduced: 1993, current_generation: 5, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['2.0L Turbo I4', '2.0L PHEV'], horsepower_range: { min: 255, max: 312 }, mpg_city: 24, mpg_highway: 33, seating_capacity: 5, cargo_volume_cf: 12.6, safety_rating: 5, features: ['MBUX', 'Digital Light', 'Rear Axle Steering'] },
    { model_id: 'MOD052', manufacturer_id: 'MFR007', brand: 'Mercedes-Benz', model_name: 'E-Class', body_type: 'Sedan', segment: 'Mid-size Luxury', base_msrp: 58750, year_introduced: 1953, current_generation: 6, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['2.0L Turbo I4', '3.0L Turbo I6', '2.0L PHEV'], horsepower_range: { min: 255, max: 429 }, mpg_city: 24, mpg_highway: 33, seating_capacity: 5, cargo_volume_cf: 13.5, safety_rating: 5, features: ['MBUX Superscreen', 'E-Active Body Control', 'Burmester Audio'] },
    { model_id: 'MOD053', manufacturer_id: 'MFR007', brand: 'Mercedes-Benz', model_name: 'GLE', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 60850, year_introduced: 1997, current_generation: 4, fuel_types: ['Gasoline', 'Diesel', 'Plug-in Hybrid'], drivetrain_options: ['AWD'], engine_options: ['2.0L Turbo I4', '3.0L Turbo I6', '4.0L V8', '2.0L PHEV'], horsepower_range: { min: 255, max: 603 }, mpg_city: 18, mpg_highway: 24, seating_capacity: 7, cargo_volume_cf: 33.3, safety_rating: 5, features: ['E-Active Body Control', 'MBUX', 'Burmester 3D Audio'] },
    { model_id: 'MOD054', manufacturer_id: 'MFR007', brand: 'Mercedes-Benz', model_name: 'EQS', body_type: 'Sedan', segment: 'Electric Luxury', base_msrp: 104400, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 329, max: 649 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 22.0, safety_rating: 5, features: ['Hyperscreen', 'Rear Axle Steering', 'Burmester 3D Sound'], ev_range_miles: 350, battery_kwh: 107.8 },
    { model_id: 'MOD055', manufacturer_id: 'MFR007', brand: 'Mercedes-Benz', model_name: 'GLS', body_type: 'SUV', segment: 'Full-size Luxury SUV', base_msrp: 86500, year_introduced: 2006, current_generation: 3, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['AWD'], engine_options: ['3.0L Turbo I6', '4.0L Twin-Turbo V8', '3.0L PHEV'], horsepower_range: { min: 362, max: 603 }, mpg_city: 16, mpg_highway: 22, seating_capacity: 7, cargo_volume_cf: 17.4, safety_rating: 5, features: ['E-Active Body Control', 'Executive Rear Seats', 'Burmester High-End Audio'] },

    // Volkswagen/Audi Models
    { model_id: 'MOD056', manufacturer_id: 'MFR005', brand: 'Volkswagen', model_name: 'ID.4', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 38995, year_introduced: 2020, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 201, max: 295 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 30.3, safety_rating: 5, features: ['IQ.Drive', 'ID.Light', 'Travel Assist'], ev_range_miles: 291, battery_kwh: 82 },
    { model_id: 'MOD057', manufacturer_id: 'MFR005', brand: 'Volkswagen', model_name: 'Atlas', body_type: 'SUV', segment: 'Full-size SUV', base_msrp: 36190, year_introduced: 2017, current_generation: 1, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.0L Turbo I4', '3.6L V6'], horsepower_range: { min: 235, max: 276 }, mpg_city: 19, mpg_highway: 25, seating_capacity: 7, cargo_volume_cf: 20.6, safety_rating: 5, features: ['IQ.Drive', 'Digital Cockpit Pro', 'Fender Premium Audio'] },
    { model_id: 'MOD058', manufacturer_id: 'MFR005', brand: 'Audi', model_name: 'A4', body_type: 'Sedan', segment: 'Compact Luxury', base_msrp: 42400, year_introduced: 1994, current_generation: 5, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.0L Turbo I4'], horsepower_range: { min: 201, max: 261 }, mpg_city: 24, mpg_highway: 32, seating_capacity: 5, cargo_volume_cf: 12.4, safety_rating: 5, features: ['Virtual Cockpit', 'MMI Touch', 'Bang & Olufsen Audio'] },
    { model_id: 'MOD059', manufacturer_id: 'MFR005', brand: 'Audi', model_name: 'Q7', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 58900, year_introduced: 2005, current_generation: 2, fuel_types: ['Gasoline'], drivetrain_options: ['AWD'], engine_options: ['2.0L Turbo I4', '3.0L Turbo V6'], horsepower_range: { min: 261, max: 335 }, mpg_city: 17, mpg_highway: 23, seating_capacity: 7, cargo_volume_cf: 14.2, safety_rating: 5, features: ['Virtual Cockpit Plus', 'Adaptive Air Suspension', 'Bang & Olufsen 3D'] },
    { model_id: 'MOD060', manufacturer_id: 'MFR005', brand: 'Audi', model_name: 'e-tron GT', body_type: 'Sedan', segment: 'Electric Luxury Performance', base_msrp: 106500, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor'], horsepower_range: { min: 522, max: 637 }, mpg_city: null, mpg_highway: null, seating_capacity: 4, cargo_volume_cf: 10.1, safety_rating: 5, features: ['Matrix LED Headlights', 'Bang & Olufsen', 'Adaptive Air Suspension'], ev_range_miles: 238, battery_kwh: 93.4 },
    { model_id: 'MOD061', manufacturer_id: 'MFR005', brand: 'Porsche', model_name: '911', body_type: 'Coupe', segment: 'Sports Car', base_msrp: 115900, year_introduced: 1964, current_generation: 8, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['3.0L Twin-Turbo Flat-6', '3.7L Twin-Turbo Flat-6', '3.6L Hybrid'], horsepower_range: { min: 379, max: 740 }, mpg_city: 17, mpg_highway: 24, seating_capacity: 4, cargo_volume_cf: 4.6, safety_rating: null, features: ['PASM', 'Sport Chrono Package', 'Porsche Active Suspension Management'] },
    { model_id: 'MOD062', manufacturer_id: 'MFR005', brand: 'Porsche', model_name: 'Cayenne', body_type: 'SUV', segment: 'Luxury Mid-size SUV', base_msrp: 75650, year_introduced: 2002, current_generation: 3, fuel_types: ['Gasoline', 'Hybrid', 'Plug-in Hybrid'], drivetrain_options: ['AWD'], engine_options: ['3.0L V6', '4.0L Twin-Turbo V8', '3.0L V6 E-Hybrid'], horsepower_range: { min: 348, max: 739 }, mpg_city: 17, mpg_highway: 22, seating_capacity: 5, cargo_volume_cf: 27.2, safety_rating: 5, features: ['Porsche Active Suspension Management', 'Rear Axle Steering', 'Burmester Audio'] },
    { model_id: 'MOD063', manufacturer_id: 'MFR005', brand: 'Porsche', model_name: 'Taycan', body_type: 'Sedan', segment: 'Electric Luxury Performance', base_msrp: 92900, year_introduced: 2019, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 402, max: 938 }, mpg_city: null, mpg_highway: null, seating_capacity: 4, cargo_volume_cf: 12.9, safety_rating: 5, features: ['800V Architecture', 'Porsche Active Suspension Management', 'Curved Display'], ev_range_miles: 318, battery_kwh: 105 },

    // Nissan Models
    { model_id: 'MOD064', manufacturer_id: 'MFR010', brand: 'Nissan', model_name: 'Altima', body_type: 'Sedan', segment: 'Mid-size', base_msrp: 28140, year_introduced: 1992, current_generation: 6, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.5L I4', '2.0L VC-Turbo I4'], horsepower_range: { min: 188, max: 248 }, mpg_city: 28, mpg_highway: 39, seating_capacity: 5, cargo_volume_cf: 15.4, safety_rating: 5, features: ['ProPILOT Assist', 'Safety Shield 360', 'Intelligent Trace Control'] },
    { model_id: 'MOD065', manufacturer_id: 'MFR010', brand: 'Nissan', model_name: 'Rogue', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 30380, year_introduced: 2007, current_generation: 3, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['1.5L VC-Turbo I3'], horsepower_range: { min: 201, max: 201 }, mpg_city: 30, mpg_highway: 37, seating_capacity: 5, cargo_volume_cf: 36.5, safety_rating: 5, features: ['ProPILOT Assist', 'Safety Shield 360', 'Divide-N-Hide Cargo'] },
    { model_id: 'MOD066', manufacturer_id: 'MFR010', brand: 'Nissan', model_name: 'Ariya', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 43190, year_introduced: 2022, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 214, max: 389 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 22.8, safety_rating: 5, features: ['e-4ORCE', 'ProPILOT Assist 2.0', 'Zero Gravity Seats'], ev_range_miles: 304, battery_kwh: 87 },
    { model_id: 'MOD067', manufacturer_id: 'MFR010', brand: 'Nissan', model_name: 'Pathfinder', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 36890, year_introduced: 1986, current_generation: 5, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', '4WD'], engine_options: ['3.5L V6'], horsepower_range: { min: 284, max: 284 }, mpg_city: 21, mpg_highway: 27, seating_capacity: 8, cargo_volume_cf: 16.6, safety_rating: 5, features: ['ProPILOT Assist', '7 Drive Modes', 'Safety Shield 360'] },
    { model_id: 'MOD068', manufacturer_id: 'MFR010', brand: 'Nissan', model_name: 'Frontier', body_type: 'Truck', segment: 'Mid-size Truck', base_msrp: 32640, year_introduced: 1997, current_generation: 3, fuel_types: ['Gasoline'], drivetrain_options: ['RWD', '4WD'], engine_options: ['3.8L V6'], horsepower_range: { min: 310, max: 310 }, mpg_city: 18, mpg_highway: 24, seating_capacity: 5, cargo_volume_cf: null, safety_rating: 5, features: ['PRO-4X Package', 'Utili-track Channel System', 'Around View Monitor'] },
    { model_id: 'MOD069', manufacturer_id: 'MFR010', brand: 'Nissan', model_name: 'LEAF', body_type: 'Hatchback', segment: 'Electric Compact', base_msrp: 28040, year_introduced: 2010, current_generation: 2, fuel_types: ['Electric'], drivetrain_options: ['FWD'], engine_options: ['Single Motor'], horsepower_range: { min: 147, max: 214 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 23.6, safety_rating: 5, features: ['e-Pedal', 'ProPILOT Assist', 'Intelligent Around View Monitor'], ev_range_miles: 212, battery_kwh: 62 },

    // Stellantis Models
    { model_id: 'MOD070', manufacturer_id: 'MFR011', brand: 'Jeep', model_name: 'Grand Cherokee', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 43735, year_introduced: 1992, current_generation: 5, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['RWD', '4WD'], engine_options: ['3.6L V6', '5.7L V8', '2.0L Turbo PHEV'], horsepower_range: { min: 293, max: 510 }, mpg_city: 19, mpg_highway: 26, seating_capacity: 5, cargo_volume_cf: 37.7, safety_rating: 5, features: ['Quadra-Lift Air Suspension', 'Selec-Terrain', 'McIntosh Audio'] },
    { model_id: 'MOD071', manufacturer_id: 'MFR011', brand: 'Jeep', model_name: 'Wrangler', body_type: 'SUV', segment: 'Compact Off-Road SUV', base_msrp: 32495, year_introduced: 1986, current_generation: 4, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['4WD'], engine_options: ['3.6L V6', '2.0L Turbo I4', '6.4L V8', '2.0L Turbo PHEV'], horsepower_range: { min: 270, max: 470 }, mpg_city: 17, mpg_highway: 23, seating_capacity: 5, cargo_volume_cf: 31.7, safety_rating: 4, features: ['Rock-Trac 4WD', 'Removable Roof', 'Locking Differentials'] },
    { model_id: 'MOD072', manufacturer_id: 'MFR011', brand: 'Ram', model_name: '1500', body_type: 'Truck', segment: 'Full-size Truck', base_msrp: 39590, year_introduced: 1981, current_generation: 5, fuel_types: ['Gasoline', 'Diesel', 'Plug-in Hybrid'], drivetrain_options: ['RWD', '4WD'], engine_options: ['3.6L V6', '5.7L HEMI V8', '3.0L EcoDiesel', '3.6L eTorque Hybrid'], horsepower_range: { min: 260, max: 702 }, mpg_city: 17, mpg_highway: 25, seating_capacity: 6, cargo_volume_cf: null, safety_rating: 5, features: ['Active-Level Four Corner Air Suspension', 'Multifunction Tailgate', '12-inch Uconnect'] },
    { model_id: 'MOD073', manufacturer_id: 'MFR011', brand: 'Dodge', model_name: 'Charger', body_type: 'Sedan', segment: 'Full-size Performance', base_msrp: 37000, year_introduced: 1966, current_generation: 7, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['400V Electric', '800V Electric'], horsepower_range: { min: 496, max: 670 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 16.2, safety_rating: null, features: ['Fratzonic Chambered Exhaust', 'PowerShot', 'Track Mode'], ev_range_miles: 317, battery_kwh: 100.5 },

    // Subaru Models
    { model_id: 'MOD074', manufacturer_id: 'MFR012', brand: 'Subaru', model_name: 'Outback', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 31990, year_introduced: 1994, current_generation: 6, fuel_types: ['Gasoline'], drivetrain_options: ['AWD'], engine_options: ['2.5L Boxer I4', '2.4L Turbo Boxer I4'], horsepower_range: { min: 182, max: 260 }, mpg_city: 26, mpg_highway: 32, seating_capacity: 5, cargo_volume_cf: 32.5, safety_rating: 5, features: ['EyeSight', 'X-MODE', 'StarTex Upholstery'] },
    { model_id: 'MOD075', manufacturer_id: 'MFR012', brand: 'Subaru', model_name: 'Forester', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 33440, year_introduced: 1997, current_generation: 6, fuel_types: ['Gasoline', 'Hybrid'], drivetrain_options: ['AWD'], engine_options: ['2.5L Boxer I4', '2.5L Hybrid'], horsepower_range: { min: 180, max: 180 }, mpg_city: 26, mpg_highway: 33, seating_capacity: 5, cargo_volume_cf: 28.9, safety_rating: 5, features: ['EyeSight', 'SI-DRIVE', 'Panoramic Moonroof'] },
    { model_id: 'MOD076', manufacturer_id: 'MFR012', brand: 'Subaru', model_name: 'Crosstrek', body_type: 'SUV', segment: 'Subcompact SUV', base_msrp: 26290, year_introduced: 2012, current_generation: 3, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['AWD'], engine_options: ['2.0L Boxer I4', '2.5L Boxer I4', '2.5L PHEV'], horsepower_range: { min: 152, max: 182 }, mpg_city: 28, mpg_highway: 34, seating_capacity: 5, cargo_volume_cf: 20.8, safety_rating: 5, features: ['EyeSight', 'X-MODE', 'Starlink'] },
    { model_id: 'MOD077', manufacturer_id: 'MFR012', brand: 'Subaru', model_name: 'Solterra', body_type: 'SUV', segment: 'Electric Compact SUV', base_msrp: 44995, year_introduced: 2022, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor'], horsepower_range: { min: 215, max: 215 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 29.0, safety_rating: 5, features: ['X-MODE', 'EyeSight', 'Multi-Terrain Select'], ev_range_miles: 228, battery_kwh: 72.8 },

    // Mazda Models
    { model_id: 'MOD078', manufacturer_id: 'MFR013', brand: 'Mazda', model_name: 'CX-5', body_type: 'SUV', segment: 'Compact SUV', base_msrp: 29300, year_introduced: 2012, current_generation: 2, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.5L SKYACTIV-G I4', '2.5L SKYACTIV-G Turbo I4'], horsepower_range: { min: 187, max: 256 }, mpg_city: 24, mpg_highway: 30, seating_capacity: 5, cargo_volume_cf: 30.8, safety_rating: 5, features: ['i-Activsense', 'Mi-Drive', 'Bose Audio'] },
    { model_id: 'MOD079', manufacturer_id: 'MFR013', brand: 'Mazda', model_name: 'CX-90', body_type: 'SUV', segment: 'Mid-size SUV', base_msrp: 40970, year_introduced: 2023, current_generation: 1, fuel_types: ['Gasoline', 'Plug-in Hybrid'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['3.3L Turbo I6', '3.3L Turbo I6 Hybrid', '2.5L PHEV'], horsepower_range: { min: 280, max: 369 }, mpg_city: 21, mpg_highway: 28, seating_capacity: 8, cargo_volume_cf: 14.9, safety_rating: 5, features: ['Kinematic Posture Control', 'i-Activsense', 'Bose Premium Audio'] },
    { model_id: 'MOD080', manufacturer_id: 'MFR013', brand: 'Mazda', model_name: 'Mazda3', body_type: 'Sedan', segment: 'Compact', base_msrp: 24970, year_introduced: 2003, current_generation: 4, fuel_types: ['Gasoline'], drivetrain_options: ['FWD', 'AWD'], engine_options: ['2.5L SKYACTIV-G I4', '2.5L SKYACTIV-G Turbo I4'], horsepower_range: { min: 191, max: 250 }, mpg_city: 26, mpg_highway: 35, seating_capacity: 5, cargo_volume_cf: 13.2, safety_rating: 5, features: ['i-Activsense', 'Mazda Connected Services', 'Bose Audio'] },
    { model_id: 'MOD081', manufacturer_id: 'MFR013', brand: 'Mazda', model_name: 'MX-5 Miata', body_type: 'Convertible', segment: 'Sports Car', base_msrp: 28985, year_introduced: 1989, current_generation: 4, fuel_types: ['Gasoline'], drivetrain_options: ['RWD'], engine_options: ['2.0L SKYACTIV-G I4'], horsepower_range: { min: 181, max: 181 }, mpg_city: 26, mpg_highway: 34, seating_capacity: 2, cargo_volume_cf: 4.6, safety_rating: 5, features: ['Bilstein Dampers', 'Limited-Slip Differential', 'Brembo Brakes'] },

    // Rivian Models
    { model_id: 'MOD082', manufacturer_id: 'MFR014', brand: 'Rivian', model_name: 'R1T', body_type: 'Truck', segment: 'Electric Mid-size Truck', base_msrp: 69900, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor', 'Quad Motor'], horsepower_range: { min: 533, max: 835 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 62.3, safety_rating: 5, features: ['Tank Turn', 'Gear Tunnel', 'Camp Kitchen'], ev_range_miles: 352, battery_kwh: 135 },
    { model_id: 'MOD083', manufacturer_id: 'MFR014', brand: 'Rivian', model_name: 'R1S', body_type: 'SUV', segment: 'Electric Mid-size SUV', base_msrp: 75900, year_introduced: 2022, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor', 'Quad Motor'], horsepower_range: { min: 533, max: 835 }, mpg_city: null, mpg_highway: null, seating_capacity: 7, cargo_volume_cf: 104.0, safety_rating: 5, features: ['Tank Turn', 'Air Compressor', 'Meridian Audio'], ev_range_miles: 321, battery_kwh: 135 },

    // Lucid Models
    { model_id: 'MOD084', manufacturer_id: 'MFR015', brand: 'Lucid', model_name: 'Air', body_type: 'Sedan', segment: 'Electric Luxury', base_msrp: 69900, year_introduced: 2021, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['RWD', 'AWD'], engine_options: ['Single Motor', 'Dual Motor'], horsepower_range: { min: 480, max: 1234 }, mpg_city: null, mpg_highway: null, seating_capacity: 5, cargo_volume_cf: 32.0, safety_rating: 5, features: ['DreamDrive', 'Glass Canopy Roof', 'Surreal Sound Pro'], ev_range_miles: 516, battery_kwh: 118 },
    { model_id: 'MOD085', manufacturer_id: 'MFR015', brand: 'Lucid', model_name: 'Gravity', body_type: 'SUV', segment: 'Electric Luxury SUV', base_msrp: 79900, year_introduced: 2024, current_generation: 1, fuel_types: ['Electric'], drivetrain_options: ['AWD'], engine_options: ['Dual Motor'], horsepower_range: { min: 620, max: 828 }, mpg_city: null, mpg_highway: null, seating_capacity: 7, cargo_volume_cf: 120.0, safety_rating: null, features: ['DreamDrive Pro', 'Executive Seating', 'Surreal Sound'], ev_range_miles: 440, battery_kwh: 113 }
];

// Add timestamps to all models
vehicleModels.forEach(model => {
    model.created_at = new Date();
    model.updated_at = new Date();
});

db.vehicle_models.insertMany(vehicleModels);
print(`Inserted ${vehicleModels.length} vehicle models`);

// ============================================================================
// 3. DEALERSHIPS
// ============================================================================

const states = ['CA', 'TX', 'FL', 'NY', 'IL', 'PA', 'OH', 'GA', 'NC', 'MI', 'NJ', 'VA', 'WA', 'AZ', 'MA', 'TN', 'IN', 'MD', 'MO', 'WI'];
const cities = {
    'CA': ['Los Angeles', 'San Diego', 'San Jose', 'San Francisco', 'Fresno', 'Sacramento', 'Long Beach', 'Oakland'],
    'TX': ['Houston', 'San Antonio', 'Dallas', 'Austin', 'Fort Worth', 'El Paso', 'Arlington', 'Plano'],
    'FL': ['Jacksonville', 'Miami', 'Tampa', 'Orlando', 'St. Petersburg', 'Hialeah', 'Tallahassee', 'Fort Lauderdale'],
    'NY': ['New York', 'Buffalo', 'Rochester', 'Yonkers', 'Syracuse', 'Albany', 'New Rochelle', 'Mount Vernon'],
    'IL': ['Chicago', 'Aurora', 'Naperville', 'Joliet', 'Rockford', 'Springfield', 'Elgin', 'Peoria'],
    'PA': ['Philadelphia', 'Pittsburgh', 'Allentown', 'Reading', 'Erie', 'Scranton', 'Bethlehem', 'Lancaster'],
    'OH': ['Columbus', 'Cleveland', 'Cincinnati', 'Toledo', 'Akron', 'Dayton', 'Parma', 'Canton'],
    'GA': ['Atlanta', 'Augusta', 'Columbus', 'Macon', 'Savannah', 'Athens', 'Sandy Springs', 'Roswell'],
    'NC': ['Charlotte', 'Raleigh', 'Greensboro', 'Durham', 'Winston-Salem', 'Fayetteville', 'Cary', 'Wilmington'],
    'MI': ['Detroit', 'Grand Rapids', 'Warren', 'Sterling Heights', 'Ann Arbor', 'Lansing', 'Flint', 'Dearborn'],
    'NJ': ['Newark', 'Jersey City', 'Paterson', 'Elizabeth', 'Edison', 'Woodbridge', 'Lakewood', 'Toms River'],
    'VA': ['Virginia Beach', 'Norfolk', 'Chesapeake', 'Richmond', 'Newport News', 'Alexandria', 'Hampton', 'Roanoke'],
    'WA': ['Seattle', 'Spokane', 'Tacoma', 'Vancouver', 'Bellevue', 'Kent', 'Everett', 'Renton'],
    'AZ': ['Phoenix', 'Tucson', 'Mesa', 'Chandler', 'Scottsdale', 'Glendale', 'Gilbert', 'Tempe'],
    'MA': ['Boston', 'Worcester', 'Springfield', 'Lowell', 'Cambridge', 'New Bedford', 'Brockton', 'Quincy'],
    'TN': ['Nashville', 'Memphis', 'Knoxville', 'Chattanooga', 'Clarksville', 'Murfreesboro', 'Franklin', 'Jackson'],
    'IN': ['Indianapolis', 'Fort Wayne', 'Evansville', 'South Bend', 'Carmel', 'Fishers', 'Bloomington', 'Hammond'],
    'MD': ['Baltimore', 'Frederick', 'Rockville', 'Gaithersburg', 'Bowie', 'Hagerstown', 'Annapolis', 'College Park'],
    'MO': ['Kansas City', 'St. Louis', 'Springfield', 'Columbia', 'Independence', 'Lee Summit', 'OFallon', 'St. Joseph'],
    'WI': ['Milwaukee', 'Madison', 'Green Bay', 'Kenosha', 'Racine', 'Appleton', 'Waukesha', 'Eau Claire']
};

const dealershipNames = ['Auto Plaza', 'Motor World', 'Car Center', 'Auto Mall', 'Motors', 'Auto Group', 'Automotive', 'Car Sales', 'Auto Sales', 'Motor Co'];
const streetNames = ['Main St', 'Oak Ave', 'Maple Dr', 'Highway 1', 'Industrial Blvd', 'Commerce Way', 'Auto Row', 'Motor Mile', 'Dealer Dr', 'Service Rd'];

const dealerships = [];
const brands = ['Toyota', 'Ford', 'Chevrolet', 'Honda', 'Nissan', 'Hyundai', 'Kia', 'BMW', 'Mercedes-Benz', 'Tesla', 'Volkswagen', 'Subaru', 'Mazda', 'Jeep', 'Ram', 'GMC', 'Cadillac', 'Lexus', 'Acura', 'Audi'];

for (let i = 1; i <= 200; i++) {
    const state = randomElement(states);
    const city = randomElement(cities[state]);
    const brand = randomElement(brands);
    const dealerName = randomElement(dealershipNames);

    dealerships.push({
        dealership_id: `DLR${String(i).padStart(4, '0')}`,
        name: `${city} ${brand} ${dealerName}`,
        brand: brand,
        address: {
            street: `${randomInt(100, 9999)} ${randomElement(streetNames)}`,
            city: city,
            state: state,
            zip_code: `${randomInt(10000, 99999)}`,
            country: 'USA'
        },
        contact: {
            phone: generatePhone(),
            email: `info@${city.toLowerCase().replace(/\s/g, '')}${brand.toLowerCase()}.com`,
            website: `https://www.${city.toLowerCase().replace(/\s/g, '')}${brand.toLowerCase()}.com`
        },
        hours: {
            monday: '9:00 AM - 8:00 PM',
            tuesday: '9:00 AM - 8:00 PM',
            wednesday: '9:00 AM - 8:00 PM',
            thursday: '9:00 AM - 8:00 PM',
            friday: '9:00 AM - 8:00 PM',
            saturday: '9:00 AM - 6:00 PM',
            sunday: '11:00 AM - 5:00 PM'
        },
        services: ['Sales', 'Service', 'Parts', randomElement(['Body Shop', 'Detailing', 'Finance', 'Leasing'])],
        employees_count: randomInt(15, 150),
        annual_sales_volume: randomInt(500, 5000),
        customer_rating: randomFloat(3.5, 5.0, 1),
        reviews_count: randomInt(50, 2000),
        certifications: randomElement([['Certified Pre-Owned'], ['Elite Dealer'], ['Customer First Award'], ['President\'s Award']]),
        inventory_capacity: randomInt(100, 500),
        service_bays: randomInt(8, 30),
        established_year: randomInt(1960, 2020),
        is_active: true,
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.dealerships.insertMany(dealerships);
print(`Inserted ${dealerships.length} dealerships`);

// ============================================================================
// 4. CUSTOMERS
// ============================================================================

const firstNames = ['James', 'Mary', 'John', 'Patricia', 'Robert', 'Jennifer', 'Michael', 'Linda', 'William', 'Elizabeth', 'David', 'Barbara', 'Richard', 'Susan', 'Joseph', 'Jessica', 'Thomas', 'Sarah', 'Charles', 'Karen', 'Christopher', 'Lisa', 'Daniel', 'Nancy', 'Matthew', 'Betty', 'Anthony', 'Margaret', 'Mark', 'Sandra', 'Donald', 'Ashley', 'Steven', 'Kimberly', 'Paul', 'Emily', 'Andrew', 'Donna', 'Joshua', 'Michelle', 'Kenneth', 'Dorothy', 'Kevin', 'Carol', 'Brian', 'Amanda', 'George', 'Melissa', 'Timothy', 'Deborah', 'Ronald', 'Stephanie', 'Edward', 'Rebecca', 'Jason', 'Sharon', 'Jeffrey', 'Laura', 'Ryan', 'Cynthia', 'Jacob', 'Kathleen', 'Gary', 'Amy', 'Nicholas', 'Angela', 'Eric', 'Shirley', 'Jonathan', 'Anna', 'Stephen', 'Brenda', 'Larry', 'Pamela', 'Justin', 'Emma', 'Scott', 'Nicole', 'Brandon', 'Helen', 'Benjamin', 'Samantha', 'Samuel', 'Katherine', 'Raymond', 'Christine', 'Gregory', 'Debra', 'Frank', 'Rachel', 'Alexander', 'Carolyn', 'Patrick', 'Janet', 'Jack', 'Catherine', 'Dennis', 'Maria', 'Jerry', 'Heather', 'Tyler', 'Diane'];
const lastNames = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez', 'Clark', 'Ramirez', 'Lewis', 'Robinson', 'Walker', 'Young', 'Allen', 'King', 'Wright', 'Scott', 'Torres', 'Nguyen', 'Hill', 'Flores', 'Green', 'Adams', 'Nelson', 'Baker', 'Hall', 'Rivera', 'Campbell', 'Mitchell', 'Carter', 'Roberts', 'Gomez', 'Phillips', 'Evans', 'Turner', 'Diaz', 'Parker', 'Cruz', 'Edwards', 'Collins', 'Reyes', 'Stewart', 'Morris', 'Morales', 'Murphy', 'Cook', 'Rogers', 'Gutierrez', 'Ortiz', 'Morgan', 'Cooper', 'Peterson', 'Bailey', 'Reed', 'Kelly', 'Howard', 'Ramos', 'Kim', 'Cox', 'Ward', 'Richardson', 'Watson', 'Brooks', 'Chavez', 'Wood', 'James', 'Bennett', 'Gray', 'Mendoza', 'Ruiz', 'Hughes', 'Price', 'Alvarez', 'Castillo', 'Sanders', 'Patel', 'Myers', 'Long', 'Ross', 'Foster', 'Jimenez'];
const emailDomains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com', 'aol.com', 'protonmail.com'];

const customers = [];
for (let i = 1; i <= 5000; i++) {
    const firstName = randomElement(firstNames);
    const lastName = randomElement(lastNames);
    const state = randomElement(states);
    const city = randomElement(cities[state]);
    const birthYear = randomInt(1950, 2005);

    customers.push({
        customer_id: `CUS${String(i).padStart(6, '0')}`,
        first_name: firstName,
        last_name: lastName,
        email: generateEmail(firstName, lastName, randomElement(emailDomains)),
        phone: generatePhone(),
        address: {
            street: `${randomInt(100, 9999)} ${randomElement(['Oak St', 'Maple Ave', 'Pine Rd', 'Cedar Ln', 'Elm Dr', 'Birch Way', 'Willow Ct', 'Spruce Blvd'])}`,
            city: city,
            state: state,
            zip_code: `${randomInt(10000, 99999)}`,
            country: 'USA'
        },
        date_of_birth: new Date(birthYear, randomInt(0, 11), randomInt(1, 28)),
        driver_license: {
            number: `${state}${randomInt(1000000, 9999999)}`,
            state: state,
            expiry_date: randomDate(2024, 2030)
        },
        credit_score: randomInt(550, 850),
        annual_income: randomInt(30000, 250000),
        employment_status: randomElement(['Employed', 'Self-Employed', 'Retired', 'Student']),
        preferred_contact_method: randomElement(['Email', 'Phone', 'Text']),
        marketing_consent: Math.random() > 0.3,
        loyalty_points: randomInt(0, 50000),
        customer_since: randomDate(2010, 2024),
        total_purchases: randomInt(0, 10),
        total_spent: randomFloat(0, 500000, 2),
        preferred_brands: [randomElement(brands), randomElement(brands)].filter((v, i, a) => a.indexOf(v) === i),
        tags: randomElement([['VIP'], ['Fleet'], ['Returning Customer'], ['First-Time Buyer'], []]),
        notes: '',
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.customers.insertMany(customers);
print(`Inserted ${customers.length} customers`);

// ============================================================================
// 5. VEHICLE INVENTORY
// ============================================================================

const exteriorColors = ['Black', 'White', 'Silver', 'Gray', 'Blue', 'Red', 'Green', 'Brown', 'Orange', 'Yellow', 'Gold', 'Pearl White', 'Midnight Blue', 'Forest Green', 'Burgundy', 'Champagne', 'Ice Silver', 'Obsidian Black', 'Crystal White', 'Lunar Silver'];
const interiorColors = ['Black', 'Gray', 'Tan', 'Brown', 'Beige', 'White', 'Red', 'Blue', 'Cream', 'Saddle Brown'];
const interiorMaterials = ['Cloth', 'Leather', 'Leatherette', 'Alcantara', 'Nappa Leather', 'Premium Cloth', 'Synthetic Leather'];
const transmissions = ['Automatic', 'Manual', 'CVT', 'DCT', 'Single-Speed'];
const conditions = ['New', 'Certified Pre-Owned', 'Used'];

const inventory = [];
const modelIds = vehicleModels.map(m => m.model_id);
const dealershipIds = dealerships.map(d => d.dealership_id);

for (let i = 1; i <= 10000; i++) {
    const model = randomElement(vehicleModels);
    const condition = randomElement(conditions);
    const modelYear = condition === 'New' ? randomInt(2024, 2025) : randomInt(2018, 2024);
    const mileage = condition === 'New' ? randomInt(5, 50) : randomInt(5000, 120000);
    const basePrice = model.base_msrp;
    const priceAdjustment = condition === 'New' ? randomFloat(0.95, 1.15) : randomFloat(0.4, 0.85);

    inventory.push({
        inventory_id: `INV${String(i).padStart(7, '0')}`,
        vin: generateVIN(),
        model_id: model.model_id,
        dealership_id: randomElement(dealershipIds),
        brand: model.brand,
        model_name: model.model_name,
        model_year: modelYear,
        body_type: model.body_type,
        trim_level: randomElement(['Base', 'LE', 'XLE', 'Limited', 'Sport', 'Premium', 'Platinum', 'GT', 'SE', 'SEL', 'Touring']),
        exterior_color: randomElement(exteriorColors),
        interior_color: randomElement(interiorColors),
        interior_material: randomElement(interiorMaterials),
        engine: randomElement(model.engine_options),
        transmission: randomElement(transmissions),
        drivetrain: randomElement(model.drivetrain_options),
        fuel_type: randomElement(model.fuel_types),
        mileage: mileage,
        condition: condition,
        msrp: Math.round(basePrice * (modelYear - 2020) / 4 * 1.02),
        selling_price: Math.round(basePrice * priceAdjustment),
        invoice_price: Math.round(basePrice * priceAdjustment * 0.92),
        holdback: Math.round(basePrice * 0.03),
        destination_charge: randomInt(995, 1595),
        documentation_fee: randomInt(199, 899),
        options: {
            packages: randomElement([['Technology Package'], ['Premium Package'], ['Sport Package'], ['Appearance Package'], []]),
            individual_options: randomElement([['Sunroof'], ['Navigation'], ['Premium Sound'], ['Heated Seats'], ['Leather Seats'], []])
        },
        options_value: randomInt(0, 8000),
        total_cost: Math.round(basePrice * priceAdjustment * 1.1),
        days_in_inventory: randomInt(1, 180),
        lot_location: `${randomElement(['A', 'B', 'C', 'D', 'E'])}${randomInt(1, 50)}`,
        status: randomElement(['Available', 'Available', 'Available', 'Reserved', 'Sold', 'In Transit']),
        title_status: condition === 'New' ? 'Clean' : randomElement(['Clean', 'Clean', 'Clean', 'Rebuilt', 'Salvage']),
        previous_owners: condition === 'New' ? 0 : randomInt(1, 4),
        accident_history: condition === 'New' ? false : Math.random() < 0.15,
        service_history_available: condition !== 'New',
        warranty: {
            basic: `${randomInt(3, 5)} years / ${randomInt(36000, 60000)} miles`,
            powertrain: `${randomInt(5, 10)} years / ${randomInt(60000, 100000)} miles`,
            corrosion: `${randomInt(5, 12)} years / unlimited miles`,
            roadside: `${randomInt(3, 5)} years / ${randomInt(36000, 60000)} miles`
        },
        features_list: model.features,
        photos_count: randomInt(10, 40),
        video_available: Math.random() > 0.5,
        stock_number: `STK${randomInt(10000, 99999)}`,
        date_received: randomDate(2023, 2024),
        last_price_update: randomDate(2024, 2024),
        views_count: randomInt(0, 5000),
        inquiries_count: randomInt(0, 100),
        test_drives_count: randomInt(0, 30),
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.inventory.insertMany(inventory);
print(`Inserted ${inventory.length} inventory items`);

// ============================================================================
// 6. SALES TRANSACTIONS
// ============================================================================

const financingTypes = ['Cash', 'Bank Financing', 'Dealer Financing', 'Lease', 'Credit Union'];
const salesPeople = [];
for (let i = 1; i <= 500; i++) {
    salesPeople.push({
        id: `EMP${String(i).padStart(5, '0')}`,
        name: `${randomElement(firstNames)} ${randomElement(lastNames)}`
    });
}

const sales = [];
const customerIds = customers.map(c => c.customer_id);
const inventoryIds = inventory.map(inv => inv.inventory_id);

for (let i = 1; i <= 15000; i++) {
    const inv = randomElement(inventory);
    const saleDate = randomDate(2020, 2024);
    const sellingPrice = inv.selling_price;
    const salesPerson = randomElement(salesPeople);
    const financingType = randomElement(financingTypes);

    let downPayment = 0;
    let loanAmount = 0;
    let apr = 0;
    let loanTerm = 0;
    let monthlyPayment = 0;

    if (financingType !== 'Cash') {
        downPayment = Math.round(sellingPrice * randomFloat(0.1, 0.3));
        loanAmount = sellingPrice - downPayment;
        apr = randomFloat(2.9, 12.9, 2);
        loanTerm = randomElement([36, 48, 60, 72, 84]);
        monthlyPayment = Math.round((loanAmount * (1 + apr/100 * loanTerm/12)) / loanTerm);
    }

    const tradeIn = Math.random() > 0.6 ? {
        vin: generateVIN(),
        year: randomInt(2010, 2022),
        make: randomElement(brands),
        model: randomElement(['Sedan', 'SUV', 'Truck']),
        mileage: randomInt(30000, 150000),
        condition: randomElement(['Excellent', 'Good', 'Fair', 'Poor']),
        allowance: randomInt(5000, 35000),
        payoff_amount: randomInt(0, 20000)
    } : null;

    const taxRate = randomFloat(5, 10, 2);
    const salesTax = Math.round(sellingPrice * taxRate / 100);
    const fees = randomInt(500, 2000);
    const totalPrice = sellingPrice + salesTax + fees - (tradeIn ? tradeIn.allowance - tradeIn.payoff_amount : 0);

    sales.push({
        sale_id: `SAL${String(i).padStart(7, '0')}`,
        inventory_id: inv.inventory_id,
        customer_id: randomElement(customerIds),
        dealership_id: inv.dealership_id,
        salesperson: salesPerson,
        sale_date: saleDate,
        delivery_date: new Date(saleDate.getTime() + randomInt(1, 14) * 24 * 60 * 60 * 1000),
        vehicle_details: {
            vin: inv.vin,
            brand: inv.brand,
            model: inv.model_name,
            year: inv.model_year,
            trim: inv.trim_level,
            color: inv.exterior_color
        },
        pricing: {
            msrp: inv.msrp,
            selling_price: sellingPrice,
            discount: inv.msrp - sellingPrice,
            trade_in_allowance: tradeIn ? tradeIn.allowance : 0,
            trade_in_payoff: tradeIn ? tradeIn.payoff_amount : 0,
            net_trade_value: tradeIn ? tradeIn.allowance - tradeIn.payoff_amount : 0,
            sales_tax: salesTax,
            tax_rate: taxRate,
            documentation_fee: randomInt(199, 699),
            registration_fee: randomInt(100, 500),
            title_fee: randomInt(50, 200),
            other_fees: fees,
            total_price: totalPrice
        },
        financing: {
            type: financingType,
            lender: financingType === 'Cash' ? null : randomElement(['Chase Auto', 'Capital One Auto', 'Wells Fargo', 'Ally Financial', 'Bank of America', 'Toyota Financial', 'Honda Financial', 'Ford Credit']),
            down_payment: downPayment,
            loan_amount: loanAmount,
            apr: apr,
            term_months: loanTerm,
            monthly_payment: monthlyPayment
        },
        trade_in: tradeIn,
        add_ons: {
            extended_warranty: Math.random() > 0.5 ? { name: 'Extended Warranty', price: randomInt(1500, 4000), term: randomElement([24, 36, 48, 60]) } : null,
            gap_insurance: Math.random() > 0.6 ? { name: 'GAP Insurance', price: randomInt(500, 1200) } : null,
            paint_protection: Math.random() > 0.7 ? { name: 'Paint Protection', price: randomInt(500, 1500) } : null,
            wheel_protection: Math.random() > 0.8 ? { name: 'Wheel & Tire Protection', price: randomInt(400, 900) } : null
        },
        profit: {
            front_end: Math.round((sellingPrice - inv.invoice_price) + inv.holdback),
            back_end: randomInt(200, 2500),
            total: Math.round((sellingPrice - inv.invoice_price) + inv.holdback + randomInt(200, 2500))
        },
        customer_satisfaction_score: randomInt(1, 10),
        referral_source: randomElement(['Walk-in', 'Internet Lead', 'Phone Call', 'Referral', 'Repeat Customer', 'Auto Show', 'Advertisement']),
        status: randomElement(['Completed', 'Completed', 'Completed', 'Pending Delivery', 'Cancelled']),
        notes: '',
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.sales.insertMany(sales);
print(`Inserted ${sales.length} sales transactions`);

// ============================================================================
// 7. SERVICE RECORDS
// ============================================================================

const serviceTypes = [
    { name: 'Oil Change', base_cost: 75, labor_hours: 0.5, category: 'Maintenance' },
    { name: 'Tire Rotation', base_cost: 50, labor_hours: 0.5, category: 'Maintenance' },
    { name: 'Brake Pad Replacement', base_cost: 350, labor_hours: 2, category: 'Repair' },
    { name: 'Brake Rotor Replacement', base_cost: 500, labor_hours: 2.5, category: 'Repair' },
    { name: 'Battery Replacement', base_cost: 200, labor_hours: 0.5, category: 'Repair' },
    { name: 'Air Filter Replacement', base_cost: 50, labor_hours: 0.25, category: 'Maintenance' },
    { name: 'Cabin Filter Replacement', base_cost: 60, labor_hours: 0.25, category: 'Maintenance' },
    { name: 'Transmission Fluid Change', base_cost: 200, labor_hours: 1, category: 'Maintenance' },
    { name: 'Coolant Flush', base_cost: 150, labor_hours: 1, category: 'Maintenance' },
    { name: 'Spark Plug Replacement', base_cost: 250, labor_hours: 1.5, category: 'Maintenance' },
    { name: 'Timing Belt Replacement', base_cost: 800, labor_hours: 4, category: 'Repair' },
    { name: 'Water Pump Replacement', base_cost: 600, labor_hours: 3, category: 'Repair' },
    { name: 'Alternator Replacement', base_cost: 500, labor_hours: 2, category: 'Repair' },
    { name: 'Starter Replacement', base_cost: 450, labor_hours: 2, category: 'Repair' },
    { name: 'AC Recharge', base_cost: 150, labor_hours: 1, category: 'Repair' },
    { name: 'AC Compressor Replacement', base_cost: 900, labor_hours: 4, category: 'Repair' },
    { name: 'Suspension Repair', base_cost: 700, labor_hours: 3, category: 'Repair' },
    { name: 'Wheel Alignment', base_cost: 120, labor_hours: 1, category: 'Maintenance' },
    { name: 'Engine Tune-Up', base_cost: 400, labor_hours: 2, category: 'Maintenance' },
    { name: 'Check Engine Light Diagnostic', base_cost: 100, labor_hours: 1, category: 'Diagnostic' },
    { name: 'Multi-Point Inspection', base_cost: 0, labor_hours: 0.5, category: 'Inspection' },
    { name: 'State Inspection', base_cost: 30, labor_hours: 0.5, category: 'Inspection' },
    { name: 'Recall Service', base_cost: 0, labor_hours: 1, category: 'Recall' },
    { name: 'Windshield Wiper Replacement', base_cost: 40, labor_hours: 0.25, category: 'Maintenance' },
    { name: 'Headlight Bulb Replacement', base_cost: 50, labor_hours: 0.5, category: 'Repair' },
    { name: 'Fuel Pump Replacement', base_cost: 700, labor_hours: 3, category: 'Repair' },
    { name: 'Oxygen Sensor Replacement', base_cost: 300, labor_hours: 1, category: 'Repair' },
    { name: 'Catalytic Converter Replacement', base_cost: 1500, labor_hours: 2, category: 'Repair' },
    { name: 'Exhaust System Repair', base_cost: 400, labor_hours: 2, category: 'Repair' },
    { name: 'Power Steering Fluid Change', base_cost: 100, labor_hours: 0.5, category: 'Maintenance' }
];

const technicians = [];
for (let i = 1; i <= 300; i++) {
    technicians.push({
        id: `TECH${String(i).padStart(4, '0')}`,
        name: `${randomElement(firstNames)} ${randomElement(lastNames)}`,
        certification: randomElement(['ASE Master', 'ASE Certified', 'Factory Trained', 'General'])
    });
}

const serviceRecords = [];
for (let i = 1; i <= 25000; i++) {
    const inv = randomElement(inventory);
    const service = randomElement(serviceTypes);
    const serviceDate = randomDate(2020, 2024);
    const laborRate = randomInt(100, 175);
    const laborCost = service.labor_hours * laborRate;
    const partsCost = service.base_cost * randomFloat(0.8, 1.2);
    const dealership = randomElement(dealerships);
    const tech = randomElement(technicians);

    serviceRecords.push({
        service_id: `SVC${String(i).padStart(7, '0')}`,
        vin: inv.vin,
        customer_id: randomElement(customerIds),
        dealership_id: dealership.dealership_id,
        vehicle_info: {
            brand: inv.brand,
            model: inv.model_name,
            year: inv.model_year,
            mileage_in: randomInt(5000, 150000)
        },
        service_date: serviceDate,
        appointment_time: `${randomInt(7, 16)}:${randomElement(['00', '30'])}`,
        service_type: service.category,
        service_name: service.name,
        description: `Performed ${service.name.toLowerCase()} service`,
        technician: tech,
        labor: {
            hours: service.labor_hours,
            rate: laborRate,
            total: Math.round(laborCost)
        },
        parts: {
            items: [{
                part_number: `PT${randomInt(100000, 999999)}`,
                name: `${service.name} Part`,
                quantity: randomInt(1, 4),
                unit_price: Math.round(partsCost / randomInt(1, 4)),
                total: Math.round(partsCost)
            }],
            total: Math.round(partsCost)
        },
        pricing: {
            labor: Math.round(laborCost),
            parts: Math.round(partsCost),
            shop_supplies: randomInt(5, 50),
            hazardous_waste_fee: randomInt(0, 25),
            discount: Math.round((laborCost + partsCost) * randomFloat(0, 0.1)),
            subtotal: Math.round(laborCost + partsCost),
            tax: Math.round((laborCost + partsCost) * 0.08),
            total: Math.round((laborCost + partsCost) * 1.08)
        },
        warranty_claim: service.category === 'Recall' || Math.random() < 0.1,
        customer_pay: service.category !== 'Recall' && Math.random() > 0.1,
        payment_method: randomElement(['Credit Card', 'Debit Card', 'Cash', 'Check', 'Financing']),
        status: randomElement(['Completed', 'Completed', 'Completed', 'In Progress', 'Scheduled', 'Waiting for Parts']),
        customer_satisfaction: randomInt(1, 5),
        follow_up_required: Math.random() < 0.1,
        recommendations: Math.random() < 0.3 ? [randomElement(serviceTypes).name] : [],
        notes: '',
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.service_records.insertMany(serviceRecords);
print(`Inserted ${serviceRecords.length} service records`);

// ============================================================================
// 8. PARTS INVENTORY
// ============================================================================

const partCategories = [
    'Engine', 'Transmission', 'Brakes', 'Suspension', 'Electrical', 'Cooling System',
    'Exhaust', 'Fuel System', 'Steering', 'Body', 'Interior', 'Filters', 'Fluids',
    'Wheels & Tires', 'Lighting', 'HVAC', 'Accessories'
];

const partNames = {
    'Engine': ['Oil Filter', 'Air Filter', 'Spark Plug', 'Timing Belt', 'Serpentine Belt', 'Engine Mount', 'Valve Cover Gasket', 'Head Gasket', 'Piston Ring Set', 'Camshaft'],
    'Transmission': ['Transmission Fluid', 'Clutch Kit', 'Flywheel', 'Torque Converter', 'Shift Solenoid', 'Transmission Mount', 'CV Axle', 'U-Joint', 'Differential Fluid'],
    'Brakes': ['Brake Pad Set', 'Brake Rotor', 'Brake Caliper', 'Brake Line', 'Brake Fluid', 'Brake Master Cylinder', 'Brake Booster', 'ABS Sensor', 'Parking Brake Cable'],
    'Suspension': ['Shock Absorber', 'Strut Assembly', 'Control Arm', 'Ball Joint', 'Tie Rod End', 'Sway Bar Link', 'Coil Spring', 'Leaf Spring', 'Bushing Kit'],
    'Electrical': ['Battery', 'Alternator', 'Starter Motor', 'Ignition Coil', 'Spark Plug Wire Set', 'Fuse', 'Relay', 'Sensor', 'Wiring Harness'],
    'Cooling System': ['Radiator', 'Water Pump', 'Thermostat', 'Coolant', 'Radiator Hose', 'Heater Core', 'Cooling Fan', 'Radiator Cap', 'Expansion Tank'],
    'Exhaust': ['Catalytic Converter', 'Muffler', 'Exhaust Pipe', 'Oxygen Sensor', 'Exhaust Manifold', 'Gasket', 'Clamp', 'Heat Shield'],
    'Fuel System': ['Fuel Pump', 'Fuel Filter', 'Fuel Injector', 'Fuel Pressure Regulator', 'Fuel Tank', 'Fuel Line', 'Throttle Body', 'Mass Air Flow Sensor'],
    'Filters': ['Oil Filter', 'Air Filter', 'Cabin Air Filter', 'Fuel Filter', 'Transmission Filter', 'PCV Valve']
};

const parts = [];
let partCounter = 1;
for (const category of partCategories) {
    const categoryParts = partNames[category] || [`${category} Part 1`, `${category} Part 2`, `${category} Part 3`];
    for (const partName of categoryParts) {
        for (let j = 0; j < randomInt(2, 5); j++) {
            const brand = randomElement(['OEM', 'Bosch', 'Denso', 'ACDelco', 'Motorcraft', 'Mopar', 'NGK', 'Continental', 'Gates', 'Moog', 'Raybestos', 'Wagner']);
            const cost = randomFloat(10, 500, 2);
            const markup = randomFloat(1.3, 2.0, 2);

            parts.push({
                part_id: `PRT${String(partCounter++).padStart(7, '0')}`,
                part_number: `${brand.substring(0, 3).toUpperCase()}${randomInt(100000, 999999)}`,
                name: partName,
                description: `${brand} ${partName} for various vehicle applications`,
                category: category,
                brand: brand,
                oem_part_number: `OEM${randomInt(1000000, 9999999)}`,
                compatible_makes: [randomElement(brands), randomElement(brands), randomElement(brands)].filter((v, i, a) => a.indexOf(v) === i),
                compatible_years: { min: randomInt(2015, 2020), max: 2025 },
                unit_of_measure: randomElement(['Each', 'Set', 'Kit', 'Pair', 'Gallon', 'Quart', 'Liter']),
                cost: cost,
                list_price: Math.round(cost * markup * 100) / 100,
                core_charge: category === 'Engine' || category === 'Electrical' ? randomInt(20, 200) : 0,
                weight_lbs: randomFloat(0.1, 50, 2),
                dimensions: {
                    length: randomFloat(1, 24, 1),
                    width: randomFloat(1, 18, 1),
                    height: randomFloat(1, 12, 1)
                },
                quantity_on_hand: randomInt(0, 100),
                quantity_on_order: randomInt(0, 50),
                reorder_point: randomInt(5, 20),
                reorder_quantity: randomInt(10, 50),
                bin_location: `${randomElement(['A', 'B', 'C', 'D', 'E'])}${randomInt(1, 20)}-${randomInt(1, 10)}`,
                supplier: {
                    id: `SUP${String(randomInt(1, 50)).padStart(3, '0')}`,
                    name: randomElement(['AutoZone Commercial', 'NAPA Auto Parts', 'OReilly Auto', 'Advance Auto', 'WorldPac', 'Parts Authority']),
                    lead_time_days: randomInt(1, 7)
                },
                warranty_months: randomInt(12, 36),
                is_active: true,
                last_sold_date: randomDate(2023, 2024),
                total_sold_ytd: randomInt(0, 500),
                total_sold_lifetime: randomInt(0, 5000),
                created_at: new Date(),
                updated_at: new Date()
            });
        }
    }
}

db.parts.insertMany(parts);
print(`Inserted ${parts.length} parts`);

// ============================================================================
// 9. EMPLOYEES
// ============================================================================

const departments = ['Sales', 'Service', 'Parts', 'Finance', 'Management', 'Administration', 'Marketing', 'IT', 'HR', 'Accounting'];
const positions = {
    'Sales': ['Sales Consultant', 'Senior Sales Consultant', 'Internet Sales Manager', 'Fleet Sales Manager', 'Sales Manager', 'General Sales Manager'],
    'Service': ['Service Technician', 'Master Technician', 'Service Advisor', 'Service Manager', 'Shop Foreman', 'Quick Lane Technician'],
    'Parts': ['Parts Specialist', 'Parts Counter Person', 'Parts Manager', 'Warehouse Specialist'],
    'Finance': ['Finance Manager', 'F&I Manager', 'Business Manager', 'Compliance Officer'],
    'Management': ['General Manager', 'Assistant General Manager', 'Operations Manager'],
    'Administration': ['Receptionist', 'Administrative Assistant', 'Title Clerk', 'Cashier'],
    'Marketing': ['Marketing Coordinator', 'Digital Marketing Specialist', 'BDC Representative', 'Customer Experience Manager'],
    'IT': ['IT Specialist', 'IT Manager', 'Systems Administrator'],
    'HR': ['HR Coordinator', 'HR Manager', 'Payroll Specialist'],
    'Accounting': ['Accountant', 'Controller', 'Accounts Payable Clerk', 'Accounts Receivable Clerk']
};

const employees = [];
for (let i = 1; i <= 2000; i++) {
    const firstName = randomElement(firstNames);
    const lastName = randomElement(lastNames);
    const department = randomElement(departments);
    const position = randomElement(positions[department]);
    const hireYear = randomInt(2000, 2024);
    const state = randomElement(states);
    const city = randomElement(cities[state]);

    let baseSalary;
    if (position.includes('Manager') || position.includes('Director')) {
        baseSalary = randomInt(70000, 150000);
    } else if (position.includes('Senior') || position.includes('Master') || position.includes('Specialist')) {
        baseSalary = randomInt(50000, 90000);
    } else {
        baseSalary = randomInt(35000, 65000);
    }

    employees.push({
        employee_id: `EMP${String(i).padStart(5, '0')}`,
        first_name: firstName,
        last_name: lastName,
        email: `${firstName.toLowerCase()}.${lastName.toLowerCase()}@dealership.com`,
        phone: generatePhone(),
        address: {
            street: `${randomInt(100, 9999)} ${randomElement(['Oak St', 'Maple Ave', 'Pine Rd', 'Cedar Ln'])}`,
            city: city,
            state: state,
            zip_code: `${randomInt(10000, 99999)}`
        },
        date_of_birth: new Date(randomInt(1960, 2000), randomInt(0, 11), randomInt(1, 28)),
        ssn_last_four: `${randomInt(1000, 9999)}`,
        dealership_id: randomElement(dealershipIds),
        department: department,
        position: position,
        hire_date: new Date(hireYear, randomInt(0, 11), randomInt(1, 28)),
        employment_status: randomElement(['Full-Time', 'Full-Time', 'Full-Time', 'Part-Time', 'Contract']),
        compensation: {
            type: department === 'Sales' ? 'Commission' : 'Salary',
            base_salary: baseSalary,
            commission_rate: department === 'Sales' ? randomFloat(15, 30, 1) : 0,
            bonus_eligible: Math.random() > 0.3
        },
        certifications: department === 'Service' ? [randomElement(['ASE A1', 'ASE A2', 'ASE A3', 'ASE A4', 'ASE A5', 'ASE Master', 'Factory Certified'])] : [],
        performance: {
            last_review_date: randomDate(2023, 2024),
            rating: randomFloat(2.5, 5.0, 1),
            goals_met_percentage: randomInt(60, 100)
        },
        training_completed: [randomElement(['Sales Training', 'Customer Service', 'Product Knowledge', 'Safety Training', 'Compliance'])],
        manager_id: i > 50 ? `EMP${String(randomInt(1, 50)).padStart(5, '0')}` : null,
        is_active: Math.random() > 0.1,
        termination_date: null,
        emergency_contact: {
            name: `${randomElement(firstNames)} ${lastName}`,
            relationship: randomElement(['Spouse', 'Parent', 'Sibling', 'Friend']),
            phone: generatePhone()
        },
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.employees.insertMany(employees);
print(`Inserted ${employees.length} employees`);

// ============================================================================
// 10. TEST DRIVES
// ============================================================================

const testDrives = [];
for (let i = 1; i <= 8000; i++) {
    const inv = randomElement(inventory);
    const customer = randomElement(customers);
    const dealership = dealerships.find(d => d.dealership_id === inv.dealership_id);
    const testDriveDate = randomDate(2022, 2024);

    testDrives.push({
        test_drive_id: `TD${String(i).padStart(7, '0')}`,
        customer_id: customer.customer_id,
        inventory_id: inv.inventory_id,
        dealership_id: inv.dealership_id,
        vehicle_info: {
            vin: inv.vin,
            brand: inv.brand,
            model: inv.model_name,
            year: inv.model_year,
            trim: inv.trim_level,
            color: inv.exterior_color
        },
        salesperson_id: randomElement(salesPeople).id,
        scheduled_date: testDriveDate,
        scheduled_time: `${randomInt(9, 18)}:${randomElement(['00', '15', '30', '45'])}`,
        actual_start_time: new Date(testDriveDate.getTime() + randomInt(0, 30) * 60 * 1000),
        actual_end_time: new Date(testDriveDate.getTime() + randomInt(30, 90) * 60 * 1000),
        duration_minutes: randomInt(15, 60),
        miles_driven: randomFloat(3, 20, 1),
        route_taken: randomElement(['Standard Route', 'Highway Route', 'City Route', 'Extended Route', 'Customer Choice']),
        license_verified: true,
        insurance_verified: true,
        customer_feedback: {
            overall_rating: randomInt(3, 5),
            comfort_rating: randomInt(3, 5),
            performance_rating: randomInt(3, 5),
            features_rating: randomInt(3, 5),
            value_rating: randomInt(3, 5),
            comments: randomElement(['Great vehicle!', 'Smooth ride', 'Love the features', 'Need to think about it', 'Very impressed', ''])
        },
        purchase_intent: randomElement(['High', 'Medium', 'Low', 'Purchased', 'Not Interested']),
        follow_up_scheduled: Math.random() > 0.3,
        follow_up_date: Math.random() > 0.3 ? new Date(testDriveDate.getTime() + randomInt(1, 7) * 24 * 60 * 60 * 1000) : null,
        converted_to_sale: Math.random() < 0.15,
        status: randomElement(['Completed', 'Completed', 'Completed', 'Scheduled', 'Cancelled', 'No Show']),
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.test_drives.insertMany(testDrives);
print(`Inserted ${testDrives.length} test drives`);

// ============================================================================
// 11. LEADS / INQUIRIES
// ============================================================================

const leadSources = ['Website', 'Phone Call', 'Walk-in', 'Email', 'Social Media', 'Referral', 'Third Party Lead', 'Auto Show', 'Direct Mail', 'TV Ad', 'Radio Ad', 'Billboard'];
const leadStatuses = ['New', 'Contacted', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost', 'Unqualified'];

const leads = [];
for (let i = 1; i <= 12000; i++) {
    const firstName = randomElement(firstNames);
    const lastName = randomElement(lastNames);
    const state = randomElement(states);
    const city = randomElement(cities[state]);
    const model = randomElement(vehicleModels);
    const leadDate = randomDate(2023, 2024);

    leads.push({
        lead_id: `LED${String(i).padStart(7, '0')}`,
        first_name: firstName,
        last_name: lastName,
        email: generateEmail(firstName, lastName, randomElement(emailDomains)),
        phone: generatePhone(),
        address: {
            city: city,
            state: state,
            zip_code: `${randomInt(10000, 99999)}`
        },
        source: randomElement(leadSources),
        campaign: randomElement(['Summer Sale', 'Year End Clearance', 'Holiday Special', 'New Model Launch', 'Trade-In Event', null]),
        dealership_id: randomElement(dealershipIds),
        assigned_to: randomElement(salesPeople).id,
        vehicle_interest: {
            brand: model.brand,
            model: model.model_name,
            body_type: model.body_type,
            new_or_used: randomElement(['New', 'Used', 'Either']),
            budget_min: randomInt(20000, 50000),
            budget_max: randomInt(50000, 100000),
            features_wanted: randomElement([['AWD'], ['Sunroof'], ['Leather Seats'], ['Navigation'], []])
        },
        trade_in_interest: Math.random() > 0.5,
        trade_in_details: Math.random() > 0.5 ? {
            year: randomInt(2015, 2022),
            make: randomElement(brands),
            model: 'Current Vehicle',
            mileage: randomInt(30000, 120000),
            condition: randomElement(['Excellent', 'Good', 'Fair'])
        } : null,
        financing_interest: Math.random() > 0.3,
        credit_application_submitted: Math.random() < 0.2,
        status: randomElement(leadStatuses),
        score: randomInt(1, 100),
        priority: randomElement(['Hot', 'Warm', 'Cold']),
        activities: [{
            type: 'Created',
            date: leadDate,
            notes: 'Lead created'
        }],
        next_action: randomElement(['Call', 'Email', 'Schedule Test Drive', 'Send Quote', 'Follow Up', null]),
        next_action_date: new Date(leadDate.getTime() + randomInt(1, 14) * 24 * 60 * 60 * 1000),
        converted_to_customer: Math.random() < 0.2,
        customer_id: Math.random() < 0.2 ? randomElement(customerIds) : null,
        lost_reason: Math.random() < 0.3 ? randomElement(['Price', 'Competitor', 'No Response', 'Bad Credit', 'Changed Mind', 'Wrong Vehicle']) : null,
        created_at: leadDate,
        updated_at: new Date()
    });
}

db.leads.insertMany(leads);
print(`Inserted ${leads.length} leads`);

// ============================================================================
// 12. FINANCING APPLICATIONS
// ============================================================================

const financingApplications = [];
for (let i = 1; i <= 6000; i++) {
    const customer = randomElement(customers);
    const inv = randomElement(inventory);
    const appDate = randomDate(2022, 2024);
    const creditScore = randomInt(500, 850);

    let status, approvalAmount, approvedRate;
    if (creditScore >= 720) {
        status = randomElement(['Approved', 'Approved', 'Approved', 'Funded']);
        approvalAmount = inv.selling_price;
        approvedRate = randomFloat(2.9, 5.9, 2);
    } else if (creditScore >= 650) {
        status = randomElement(['Approved', 'Approved', 'Conditional', 'Funded']);
        approvalAmount = inv.selling_price * randomFloat(0.8, 1.0);
        approvedRate = randomFloat(5.9, 9.9, 2);
    } else if (creditScore >= 580) {
        status = randomElement(['Approved', 'Conditional', 'Conditional', 'Declined']);
        approvalAmount = inv.selling_price * randomFloat(0.6, 0.8);
        approvedRate = randomFloat(9.9, 15.9, 2);
    } else {
        status = randomElement(['Declined', 'Declined', 'Conditional']);
        approvalAmount = status !== 'Declined' ? inv.selling_price * randomFloat(0.4, 0.6) : 0;
        approvedRate = status !== 'Declined' ? randomFloat(15.9, 24.9, 2) : 0;
    }

    financingApplications.push({
        application_id: `FIN${String(i).padStart(7, '0')}`,
        customer_id: customer.customer_id,
        dealership_id: randomElement(dealershipIds),
        inventory_id: inv.inventory_id,
        application_date: appDate,
        applicant: {
            first_name: customer.first_name,
            last_name: customer.last_name,
            ssn_last_four: `${randomInt(1000, 9999)}`,
            date_of_birth: customer.date_of_birth,
            phone: customer.phone,
            email: customer.email,
            address: customer.address
        },
        employment: {
            employer_name: randomElement(['Tech Corp', 'Healthcare Inc', 'Retail Co', 'Manufacturing LLC', 'Services Group', 'Self-Employed']),
            position: randomElement(['Manager', 'Engineer', 'Analyst', 'Sales', 'Driver', 'Owner', 'Technician']),
            years_employed: randomInt(0, 30),
            monthly_income: randomInt(3000, 20000),
            income_type: randomElement(['Salary', 'Hourly', 'Commission', 'Self-Employment'])
        },
        co_applicant: Math.random() < 0.3 ? {
            first_name: randomElement(firstNames),
            last_name: customer.last_name,
            relationship: randomElement(['Spouse', 'Parent', 'Partner']),
            monthly_income: randomInt(2000, 15000)
        } : null,
        vehicle_info: {
            vin: inv.vin,
            brand: inv.brand,
            model: inv.model_name,
            year: inv.model_year,
            selling_price: inv.selling_price
        },
        loan_request: {
            amount: inv.selling_price,
            down_payment: Math.round(inv.selling_price * randomFloat(0.05, 0.25)),
            term_months: randomElement([36, 48, 60, 72, 84]),
            trade_in_value: Math.random() < 0.4 ? randomInt(5000, 30000) : 0
        },
        credit_info: {
            score: creditScore,
            score_source: randomElement(['Equifax', 'Experian', 'TransUnion']),
            bankruptcy_history: creditScore < 600 && Math.random() < 0.2,
            repossession_history: creditScore < 600 && Math.random() < 0.1
        },
        lenders_submitted: [
            randomElement(['Chase Auto', 'Capital One', 'Ally Financial', 'Wells Fargo', 'Bank of America']),
            randomElement(['Toyota Financial', 'Honda Financial', 'Ford Credit', 'GM Financial'])
        ],
        status: status,
        approval_details: status !== 'Declined' ? {
            lender: randomElement(['Chase Auto', 'Capital One', 'Ally Financial', 'Manufacturer Finance']),
            approved_amount: Math.round(approvalAmount),
            approved_rate: approvedRate,
            approved_term: randomElement([48, 60, 72, 84]),
            conditions: status === 'Conditional' ? ['Proof of Income', 'Proof of Residence'] : [],
            expiration_date: new Date(appDate.getTime() + 30 * 24 * 60 * 60 * 1000)
        } : null,
        decline_reason: status === 'Declined' ? randomElement(['Low Credit Score', 'High DTI', 'Insufficient Income', 'Negative Credit History']) : null,
        documents_received: {
            drivers_license: true,
            proof_of_income: Math.random() > 0.2,
            proof_of_residence: Math.random() > 0.3,
            insurance: Math.random() > 0.4
        },
        funded_date: status === 'Funded' ? new Date(appDate.getTime() + randomInt(1, 14) * 24 * 60 * 60 * 1000) : null,
        created_at: appDate,
        updated_at: new Date()
    });
}

db.financing_applications.insertMany(financingApplications);
print(`Inserted ${financingApplications.length} financing applications`);

// ============================================================================
// 13. MARKETING CAMPAIGNS
// ============================================================================

const campaigns = [];
const campaignTypes = ['Email', 'Direct Mail', 'Digital Ads', 'Social Media', 'TV', 'Radio', 'Billboard', 'Event'];

for (let i = 1; i <= 100; i++) {
    const startDate = randomDate(2022, 2024);
    const campaignType = randomElement(campaignTypes);

    campaigns.push({
        campaign_id: `CAM${String(i).padStart(4, '0')}`,
        name: `${randomElement(['Summer', 'Winter', 'Spring', 'Fall', 'Holiday', 'Year-End', 'Memorial Day', 'Labor Day', 'Black Friday'])} ${randomElement(['Sale', 'Event', 'Clearance', 'Special', 'Promotion'])} ${startDate.getFullYear()}`,
        type: campaignType,
        description: `${campaignType} marketing campaign for vehicle sales`,
        start_date: startDate,
        end_date: new Date(startDate.getTime() + randomInt(7, 60) * 24 * 60 * 60 * 1000),
        budget: randomInt(5000, 100000),
        actual_spend: randomInt(4000, 95000),
        target_audience: {
            demographics: randomElement([['25-34'], ['35-44'], ['45-54'], ['55+'], ['All Adults']]),
            locations: [randomElement(states), randomElement(states)],
            interests: randomElement([['New Car Buyers'], ['Truck Enthusiasts'], ['Luxury Buyers'], ['EV Interested'], ['Family Vehicles']])
        },
        vehicles_featured: [randomElement(brands), randomElement(brands)],
        offers: {
            discount_type: randomElement(['Percentage', 'Cash Back', 'APR Special', 'Lease Special']),
            discount_value: randomElement(['0% APR', '$5,000 Cash Back', '20% Off MSRP', '$199/month Lease']),
            conditions: 'With approved credit. See dealer for details.'
        },
        metrics: {
            impressions: randomInt(10000, 1000000),
            clicks: randomInt(100, 50000),
            leads_generated: randomInt(10, 500),
            test_drives: randomInt(5, 200),
            sales_attributed: randomInt(1, 50),
            revenue_attributed: randomInt(30000, 2000000),
            roi: randomFloat(-20, 300, 1)
        },
        channels: campaignType === 'Digital Ads' ? ['Google Ads', 'Facebook', 'Instagram'] :
                  campaignType === 'Social Media' ? ['Facebook', 'Instagram', 'TikTok', 'YouTube'] :
                  [campaignType],
        status: randomElement(['Active', 'Completed', 'Completed', 'Completed', 'Paused', 'Scheduled']),
        created_by: `EMP${String(randomInt(1, 50)).padStart(5, '0')}`,
        created_at: new Date(),
        updated_at: new Date()
    });
}

db.campaigns.insertMany(campaigns);
print(`Inserted ${campaigns.length} marketing campaigns`);

// ============================================================================
// 14. VEHICLE APPRAISALS (Trade-In Valuations)
// ============================================================================

const appraisals = [];
for (let i = 1; i <= 5000; i++) {
    const customer = randomElement(customers);
    const appraisalDate = randomDate(2022, 2024);
    const vehicleYear = randomInt(2010, 2023);
    const mileage = randomInt(10000, 180000);
    const condition = randomElement(['Excellent', 'Good', 'Fair', 'Poor']);

    let baseValue;
    if (vehicleYear >= 2021) baseValue = randomInt(25000, 60000);
    else if (vehicleYear >= 2018) baseValue = randomInt(15000, 40000);
    else if (vehicleYear >= 2015) baseValue = randomInt(8000, 25000);
    else baseValue = randomInt(3000, 15000);

    const conditionMultiplier = condition === 'Excellent' ? 1.1 : condition === 'Good' ? 1.0 : condition === 'Fair' ? 0.85 : 0.7;
    const mileageAdjustment = mileage > 100000 ? -3000 : mileage > 75000 ? -1500 : mileage > 50000 ? -500 : 500;
    const marketValue = Math.round((baseValue * conditionMultiplier) + mileageAdjustment);

    appraisals.push({
        appraisal_id: `APR${String(i).padStart(6, '0')}`,
        customer_id: customer.customer_id,
        dealership_id: randomElement(dealershipIds),
        appraisal_date: appraisalDate,
        appraiser_id: `EMP${String(randomInt(1, 100)).padStart(5, '0')}`,
        vehicle_info: {
            vin: generateVIN(),
            year: vehicleYear,
            make: randomElement(brands),
            model: randomElement(['Sedan', 'SUV', 'Truck', 'Coupe', 'Hatchback']),
            trim: randomElement(['Base', 'LE', 'XLE', 'Limited', 'Sport']),
            mileage: mileage,
            exterior_color: randomElement(exteriorColors),
            interior_color: randomElement(interiorColors)
        },
        condition_report: {
            overall_condition: condition,
            exterior: {
                paint: randomElement(['Excellent', 'Good', 'Fair', 'Poor']),
                body_panels: randomElement(['No Damage', 'Minor Dents', 'Moderate Damage', 'Significant Damage']),
                glass: randomElement(['No Damage', 'Chip', 'Crack']),
                lights: randomElement(['Working', 'Needs Repair'])
            },
            interior: {
                seats: randomElement(['Excellent', 'Good', 'Worn', 'Damaged']),
                carpet: randomElement(['Clean', 'Stained', 'Worn']),
                dashboard: randomElement(['No Damage', 'Cracked', 'Faded']),
                electronics: randomElement(['All Working', 'Some Issues', 'Not Working'])
            },
            mechanical: {
                engine: randomElement(['Runs Great', 'Runs Well', 'Needs Work', 'Not Running']),
                transmission: randomElement(['Shifts Smoothly', 'Rough Shifting', 'Slipping']),
                brakes: randomElement(['Good', 'Fair', 'Needs Replacement']),
                tires: `${randomInt(20, 100)}% tread remaining`
            }
        },
        accident_history: Math.random() < 0.2,
        title_status: randomElement(['Clean', 'Clean', 'Clean', 'Salvage', 'Rebuilt']),
        service_records_available: Math.random() > 0.5,
        valuation: {
            kbb_value: marketValue + randomInt(-2000, 2000),
            nada_value: marketValue + randomInt(-2000, 2000),
            auction_value: Math.round(marketValue * 0.85),
            retail_value: Math.round(marketValue * 1.15),
            offered_value: Math.round(marketValue * randomFloat(0.85, 0.95)),
            final_value: Math.round(marketValue * randomFloat(0.85, 0.95))
        },
        reconditioning_estimate: randomInt(500, 5000),
        payoff_amount: Math.random() < 0.4 ? randomInt(5000, marketValue * 0.8) : 0,
        equity: 0,
        status: randomElement(['Pending', 'Completed', 'Completed', 'Completed', 'Expired', 'Traded']),
        valid_until: new Date(appraisalDate.getTime() + 7 * 24 * 60 * 60 * 1000),
        photos_taken: randomInt(10, 30),
        notes: '',
        created_at: appraisalDate,
        updated_at: new Date()
    });
}

db.appraisals.insertMany(appraisals);
print(`Inserted ${appraisals.length} appraisals`);

// ============================================================================
// 15. WARRANTY CLAIMS
// ============================================================================

const warrantyClaims = [];
for (let i = 1; i <= 3000; i++) {
    const serviceRecord = randomElement(serviceRecords);
    const claimDate = randomDate(2022, 2024);
    const laborCost = randomInt(100, 1500);
    const partsCost = randomInt(50, 3000);

    warrantyClaims.push({
        claim_id: `WCL${String(i).padStart(6, '0')}`,
        service_id: serviceRecord.service_id,
        vin: serviceRecord.vin,
        dealership_id: serviceRecord.dealership_id,
        claim_date: claimDate,
        warranty_type: randomElement(['Basic', 'Powertrain', 'Extended', 'CPO', 'Dealer']),
        claim_type: randomElement(['Parts', 'Labor', 'Parts and Labor', 'Goodwill']),
        description: serviceRecord.service_name,
        failure_code: `FC${randomInt(1000, 9999)}`,
        repair_code: `RC${randomInt(1000, 9999)}`,
        mileage_at_claim: randomInt(5000, 60000),
        labor: {
            hours: randomFloat(0.5, 8, 1),
            rate: randomInt(80, 150),
            amount: laborCost
        },
        parts: [{
            part_number: `PT${randomInt(100000, 999999)}`,
            description: 'Warranty Replacement Part',
            quantity: randomInt(1, 3),
            cost: partsCost
        }],
        total_claim_amount: laborCost + partsCost,
        approved_amount: Math.round((laborCost + partsCost) * randomFloat(0.8, 1.0)),
        customer_responsibility: randomInt(0, 200),
        status: randomElement(['Submitted', 'Under Review', 'Approved', 'Approved', 'Approved', 'Paid', 'Paid', 'Denied']),
        denial_reason: null,
        payment_date: null,
        manufacturer_reference: `MFR${randomInt(100000000, 999999999)}`,
        created_at: claimDate,
        updated_at: new Date()
    });
}

db.warranty_claims.insertMany(warrantyClaims);
print(`Inserted ${warrantyClaims.length} warranty claims`);

// ============================================================================
// CREATE INDEXES
// ============================================================================

print('Creating indexes...');

// Manufacturers indexes
db.manufacturers.createIndex({ manufacturer_id: 1 }, { unique: true });
db.manufacturers.createIndex({ name: 1 });

// Vehicle models indexes
db.vehicle_models.createIndex({ model_id: 1 }, { unique: true });
db.vehicle_models.createIndex({ manufacturer_id: 1 });
db.vehicle_models.createIndex({ brand: 1, model_name: 1 });
db.vehicle_models.createIndex({ body_type: 1 });
db.vehicle_models.createIndex({ segment: 1 });
db.vehicle_models.createIndex({ base_msrp: 1 });

// Dealerships indexes
db.dealerships.createIndex({ dealership_id: 1 }, { unique: true });
db.dealerships.createIndex({ brand: 1 });
db.dealerships.createIndex({ 'address.state': 1, 'address.city': 1 });
db.dealerships.createIndex({ customer_rating: -1 });

// Customers indexes
db.customers.createIndex({ customer_id: 1 }, { unique: true });
db.customers.createIndex({ email: 1 });
db.customers.createIndex({ 'address.state': 1 });
db.customers.createIndex({ credit_score: 1 });
db.customers.createIndex({ customer_since: 1 });

// Inventory indexes
db.inventory.createIndex({ inventory_id: 1 }, { unique: true });
db.inventory.createIndex({ vin: 1 }, { unique: true });
db.inventory.createIndex({ dealership_id: 1 });
db.inventory.createIndex({ brand: 1, model_name: 1 });
db.inventory.createIndex({ model_year: 1 });
db.inventory.createIndex({ selling_price: 1 });
db.inventory.createIndex({ condition: 1 });
db.inventory.createIndex({ status: 1 });
db.inventory.createIndex({ body_type: 1 });
db.inventory.createIndex({ fuel_type: 1 });

// Sales indexes
db.sales.createIndex({ sale_id: 1 }, { unique: true });
db.sales.createIndex({ customer_id: 1 });
db.sales.createIndex({ dealership_id: 1 });
db.sales.createIndex({ sale_date: 1 });
db.sales.createIndex({ 'salesperson.id': 1 });
db.sales.createIndex({ 'vehicle_details.brand': 1 });
db.sales.createIndex({ 'pricing.total_price': 1 });

// Service records indexes
db.service_records.createIndex({ service_id: 1 }, { unique: true });
db.service_records.createIndex({ vin: 1 });
db.service_records.createIndex({ customer_id: 1 });
db.service_records.createIndex({ dealership_id: 1 });
db.service_records.createIndex({ service_date: 1 });
db.service_records.createIndex({ service_type: 1 });

// Parts indexes
db.parts.createIndex({ part_id: 1 }, { unique: true });
db.parts.createIndex({ part_number: 1 });
db.parts.createIndex({ category: 1 });
db.parts.createIndex({ brand: 1 });
db.parts.createIndex({ quantity_on_hand: 1 });

// Employees indexes
db.employees.createIndex({ employee_id: 1 }, { unique: true });
db.employees.createIndex({ dealership_id: 1 });
db.employees.createIndex({ department: 1 });
db.employees.createIndex({ position: 1 });
db.employees.createIndex({ is_active: 1 });

// Test drives indexes
db.test_drives.createIndex({ test_drive_id: 1 }, { unique: true });
db.test_drives.createIndex({ customer_id: 1 });
db.test_drives.createIndex({ dealership_id: 1 });
db.test_drives.createIndex({ scheduled_date: 1 });
db.test_drives.createIndex({ converted_to_sale: 1 });

// Leads indexes
db.leads.createIndex({ lead_id: 1 }, { unique: true });
db.leads.createIndex({ dealership_id: 1 });
db.leads.createIndex({ status: 1 });
db.leads.createIndex({ source: 1 });
db.leads.createIndex({ created_at: 1 });
db.leads.createIndex({ priority: 1 });

// Financing applications indexes
db.financing_applications.createIndex({ application_id: 1 }, { unique: true });
db.financing_applications.createIndex({ customer_id: 1 });
db.financing_applications.createIndex({ dealership_id: 1 });
db.financing_applications.createIndex({ status: 1 });
db.financing_applications.createIndex({ application_date: 1 });

// Campaigns indexes
db.campaigns.createIndex({ campaign_id: 1 }, { unique: true });
db.campaigns.createIndex({ type: 1 });
db.campaigns.createIndex({ status: 1 });
db.campaigns.createIndex({ start_date: 1 });

// Appraisals indexes
db.appraisals.createIndex({ appraisal_id: 1 }, { unique: true });
db.appraisals.createIndex({ customer_id: 1 });
db.appraisals.createIndex({ dealership_id: 1 });
db.appraisals.createIndex({ status: 1 });

// Warranty claims indexes
db.warranty_claims.createIndex({ claim_id: 1 }, { unique: true });
db.warranty_claims.createIndex({ vin: 1 });
db.warranty_claims.createIndex({ dealership_id: 1 });
db.warranty_claims.createIndex({ status: 1 });
db.warranty_claims.createIndex({ claim_date: 1 });

print('Indexes created successfully');

// ============================================================================
// SUMMARY
// ============================================================================

print('\n============================================');
print('AUTOMOBILE DATABASE INITIALIZATION COMPLETE');
print('============================================');
print(`Manufacturers: ${db.manufacturers.countDocuments()}`);
print(`Vehicle Models: ${db.vehicle_models.countDocuments()}`);
print(`Dealerships: ${db.dealerships.countDocuments()}`);
print(`Customers: ${db.customers.countDocuments()}`);
print(`Inventory: ${db.inventory.countDocuments()}`);
print(`Sales: ${db.sales.countDocuments()}`);
print(`Service Records: ${db.service_records.countDocuments()}`);
print(`Parts: ${db.parts.countDocuments()}`);
print(`Employees: ${db.employees.countDocuments()}`);
print(`Test Drives: ${db.test_drives.countDocuments()}`);
print(`Leads: ${db.leads.countDocuments()}`);
print(`Financing Applications: ${db.financing_applications.countDocuments()}`);
print(`Marketing Campaigns: ${db.campaigns.countDocuments()}`);
print(`Appraisals: ${db.appraisals.countDocuments()}`);
print(`Warranty Claims: ${db.warranty_claims.countDocuments()}`);
print('============================================\n');
