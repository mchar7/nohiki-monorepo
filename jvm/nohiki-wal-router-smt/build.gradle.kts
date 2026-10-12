import com.github.spotbugs.snom.Confidence
import com.github.spotbugs.snom.Effort
import net.ltgt.gradle.errorprone.errorprone

plugins {
    `java-library`
    jacoco
    id("com.diffplug.spotless") version "8.9.0"
    id("net.ltgt.errorprone") version "5.1.0"
    id("com.github.spotbugs") version "6.5.9"
    id("com.gradleup.shadow") version "9.4.1"
}

group = "ai.nohiki"
version = "0.1.0"

java {
    toolchain {
        // Build with the current LTS JDK while retaining the Java 21 runtime contract.
        languageVersion.set(JavaLanguageVersion.of(25))
    }
}

// Emit bytecode compatible with the Debezium 3.6 runtime (OpenJDK 21).
// Decouples build-time JDK from runtime JDK.
tasks.withType<JavaCompile>().configureEach {
    options.release.set(21)
    options.compilerArgs.addAll(listOf("-Xlint:all", "-Werror"))
    options.errorprone {
        error("NullAway")
        error("UnusedMethod")
        error("UnusedNestedClass")
        error("UnusedTypeParameter")
        error("UnusedVariable")
        option("NullAway:OnlyNullMarked", "true")
        option("NullAway:JSpecifyMode", "true")
        option("NullAway:HandleTestAssertionLibraries", "true")
    }
}

jacoco {
    toolVersion = "0.8.15"
}

repositories {
    mavenCentral()
}

// Compile against the Kafka Connect version used to build Debezium 3.6.1.Final.
val kafkaVersion = "4.3.0"
val jacksonVersion = "2.22.1"
val slf4jVersion = "2.0.18"

dependencies {
    compileOnly("org.apache.kafka:connect-api:$kafkaVersion")
    compileOnly("org.apache.kafka:connect-transforms:$kafkaVersion")
    compileOnly("org.slf4j:slf4j-api:$slf4jVersion")
    compileOnly("org.jspecify:jspecify:1.0.1")

    // jackson-jr-objects: ~106 KB vs jackson-databind's ~1.6 MB. Purpose-built
    // for Map<String, Object> parsing of small JSON envelopes.
    implementation("com.fasterxml.jackson.jr:jackson-jr-objects:$jacksonVersion")
    errorprone("com.google.errorprone:error_prone_core:2.50.0")
    errorprone("com.uber.nullaway:nullaway:0.13.8")

    testImplementation("org.apache.kafka:connect-api:$kafkaVersion")
    testImplementation("org.apache.kafka:connect-transforms:$kafkaVersion")
    testImplementation("org.slf4j:slf4j-simple:$slf4jVersion")
    testCompileOnly("org.jspecify:jspecify:1.0.1")
    testImplementation(platform("org.junit:junit-bom:6.1.2"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testImplementation("org.junit.platform:junit-platform-launcher")
    testImplementation("org.assertj:assertj-core:3.27.7")
}

spotless {
    java {
        googleJavaFormat("1.36.1")
    }
}

spotbugs {
    toolVersion = "4.10.3"
    ignoreFailures = false
    runOnCheck = true
    effort = Effort.MAX
    reportLevel = Confidence.LOW
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
