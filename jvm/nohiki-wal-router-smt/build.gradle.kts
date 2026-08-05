plugins {
    `java-library`
    jacoco
    id("com.gradleup.shadow") version "9.4.1"
}

group = "ai.nohiki"
version = "0.1.0"

java {
    toolchain {
        // Build on the newest LTS JDK for latest compiler/tooling.
        languageVersion.set(JavaLanguageVersion.of(25))
    }
}

// Emit bytecode compatible with the Debezium 3.6 runtime (OpenJDK 21).
// Decouples build-time JDK from runtime JDK.
tasks.withType<JavaCompile>().configureEach {
    options.release.set(21)
}

jacoco {
    toolVersion = "0.8.14"
}

repositories {
    mavenCentral()
}

// Kafka Connect API pinned to match the runtime (Debezium 3.6 ships Kafka 4.1.x).
// Public Transformation/ConfigDef/Struct/Schema APIs used here are stable since 2.x.
val kafkaVersion = "4.1.0"
val jacksonVersion = "2.19.0"
val slf4jVersion = "2.0.17"

dependencies {
    compileOnly("org.apache.kafka:connect-api:$kafkaVersion")
    compileOnly("org.apache.kafka:connect-transforms:$kafkaVersion")
    compileOnly("org.slf4j:slf4j-api:$slf4jVersion")

    // jackson-jr-objects: ~106 KB vs jackson-databind's ~1.6 MB. Purpose-built
    // for Map<String, Object> parsing of small JSON envelopes.
    implementation("com.fasterxml.jackson.jr:jackson-jr-objects:$jacksonVersion")

    testImplementation("org.apache.kafka:connect-api:$kafkaVersion")
    testImplementation("org.apache.kafka:connect-transforms:$kafkaVersion")
    testImplementation("org.slf4j:slf4j-simple:$slf4jVersion")
    testImplementation(platform("org.junit:junit-bom:6.0.3"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testImplementation("org.junit.platform:junit-platform-launcher")
    testImplementation("org.assertj:assertj-core:3.27.3")
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = false
    }
    finalizedBy(tasks.jacocoTestReport)
}

tasks.jacocoTestReport {
    dependsOn(tasks.test)
    reports {
        xml.required.set(true)
        html.required.set(true)
    }
}

tasks.jacocoTestCoverageVerification {
    dependsOn(tasks.jacocoTestReport)
    violationRules {
        rule {
            limit {
                counter = "LINE"
                minimum = "0.95".toBigDecimal()
            }
            limit {
                counter = "BRANCH"
                minimum = "0.90".toBigDecimal()
            }
            limit {
                counter = "INSTRUCTION"
                minimum = "0.95".toBigDecimal()
            }
        }
    }
}

tasks.check {
    dependsOn(tasks.jacocoTestCoverageVerification)
}

tasks.shadowJar {
    // Relocate Jackson to avoid classloader collisions with the version bundled
    // by Kafka Connect / Debezium at runtime.
    relocate("com.fasterxml.jackson", "ai.nohiki.kafka.connect.shaded.jackson")
    mergeServiceFiles()
}

tasks.build {
    dependsOn(tasks.shadowJar)
}
