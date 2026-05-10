# --- Provider Configuration ---
provider "google" {
  project = "project-cdd074dc-6291-4d7f-a2a" # CHANGE THIS
  region  = "us-central1"
}

# --- Networking ---
resource "google_compute_network" "main_vpc" {
  name                    = "ping-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "us-central1-subnet"
  ip_cidr_range = "10.0.1.0/24"
  region        = "us-central1"
  network       = google_compute_network.main_vpc.id
}

# Required for Private IP Google Services (Redis/Postgres)
resource "google_compute_global_address" "private_ip_alloc" {
  name          = "private-ip-alloc"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main_vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.main_vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
}

# --- Firewall Rules ---

# 4.1: Allow all internal TCP traffic within the subnet
resource "google_compute_firewall" "allow_internal_tcp" {
  name    = "allow-internal-tcp"
  network = google_compute_network.main_vpc.id

  allow {
    protocol = "tcp"
    # No ports specified means ALL ports are allowed
  }

  source_ranges = ["10.0.1.0/24"]
}

# 4.2: Allow public ingress on ports 80, 6379, 5732 for GCE
resource "google_compute_firewall" "allow_public_ingress" {
  name    = "allow-public-gce-ingress"
  network = google_compute_network.main_vpc.id

  allow {
    protocol = "tcp"
    ports    = ["80", "5732", "6379"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["public-gce"]
}


# --- Compute Engine (GCE) ---
resource "google_compute_instance" "app_server" {
  name         = "ping-gce-01"
  zone         = "us-central1-c"
  # e2-small = 2 vCPUs (shared core), 2GB RAM.
  machine_type = "e2-small" 
  tags         = ["public-gce"]

  boot_disk {
    initialize_params {
      image  = "debian-cloud/debian-11"
      size   = 20
      type   = "pd-balanced"
    }
  }

  network_interface {
    network    = google_compute_network.main_vpc.id
    subnetwork = google_compute_subnetwork.subnet.id
    
    # This empty block gives the VM an ephemeral Public IP
    access_config {}
  }

metadata_startup_script = <<-EOF
    #!/bin/bash
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release nano unzip

    # 1. Install Docker
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
    
    # 2. Install AWS CLI v2
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    sudo ./aws/install

    
  EOF

  service_account {
    scopes = ["cloud-platform"]
  }
}

# --- Redis (Memorystore) ---
resource "google_redis_instance" "cache" {
  name               = "ping-redis"
  tier               = "BASIC"
  memory_size_gb     = 8
  region             = "us-central1"
  location_id        = "us-central1-c"
  authorized_network = google_compute_network.main_vpc.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  redis_version      = "REDIS_6_X"

  depends_on = [google_service_networking_connection.private_vpc_connection]
}

# --- PostgreSQL (Cloud SQL) ---
resource "google_sql_database_instance" "postgres" {
  name             = "ping-postgres-${random_id.db_name_suffix.hex}"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    # db-standard-2 (2 vCPU, 7.5GB RAM). Better suited for load testing 
    # than f1-micro, without paying for heavy enterprise tiers.
    tier              = "db-standard-2" 
    availability_type = "ZONAL"
    
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main_vpc.id
    }

    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = false 
  depends_on          = [google_service_networking_connection.private_vpc_connection]
}

resource "random_id" "db_name_suffix" {
  byte_length = 4
}